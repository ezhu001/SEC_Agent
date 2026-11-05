import json
import os
from pathlib import Path

import pytest
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.services.cache import atomic_json
from financial_filing_agent.services.pipeline import Pipeline
from evaluation.doubles import ScriptedDecoder, DemoRetriever


def pipeline(tmp_path):
    return Pipeline(Settings(artifact_dir=tmp_path), ScriptedDecoder(), DemoRetriever())


def test_transient_windows_replace_error_retries_and_preserves_utf8(tmp_path, monkeypatch):
    import financial_filing_agent.services.cache as cache
    real = cache.os.replace
    attempts = []
    def replace(source, dest):
        attempts.append(dest)
        if len(attempts) < 3:
            raise PermissionError("simulated Windows sharing violation")
        return real(source, dest)
    monkeypatch.setattr(cache.os, "replace", replace)
    monkeypatch.setattr(cache.time, "sleep", lambda _: None)
    path = tmp_path / "audit.json"
    atomic_json(path, {"reason": "中文 — company’s “revenue”"})
    assert len(attempts) == 3
    assert json.loads(path.read_text(encoding="utf-8"))["reason"].endswith("“revenue”")
    assert not list(tmp_path.glob("*.tmp"))


def test_locked_canonical_audit_uses_full_recovery_snapshot(tmp_path, monkeypatch):
    import financial_filing_agent.services.cache as cache
    real = cache.os.replace
    def replace(source, dest):
        if Path(dest).name == "audit.json":
            raise PermissionError("audit.json is locked")
        return real(source, dest)
    monkeypatch.setattr(cache.os, "replace", replace)
    monkeypatch.setattr(cache.time, "sleep", lambda _: None)
    result = pipeline(tmp_path).run("Revenue growth FY2025 FY2024 — 中文“测试”", "evaluation/fixtures/demo.html")
    assert result["final_status"] == "SUCCESS"
    assert result["audit_complete"]
    assert Path(result["audit_path"]).name.startswith("audit-recovery-")
    saved = json.loads(Path(result["audit_path"]).read_text(encoding="utf-8"))
    assert saved["state"]["final_status"] == "SUCCESS"
    assert saved["state"]["audit_path"] == result["audit_path"]
    assert saved["state"]["audit_events"][-1]["node"] == "finish"
    assert saved["decoder_calls"]
    assert any("recovery snapshot" in w for w in result["warnings"])


def test_all_audit_paths_denied_returns_error_without_masking(tmp_path, monkeypatch):
    import financial_filing_agent.services.audit as audit
    def denied(*args, **kwargs):
        raise PermissionError("original audit filesystem failure — 中文")
    monkeypatch.setattr(audit, "atomic_json", denied)
    result = pipeline(tmp_path).run("Revenue FY2025 FY2024", "evaluation/fixtures/demo.html")
    assert result["final_status"] == "ERROR"
    assert result["calculation_result"] is None
    assert result["final_response"]["status"] == "ERROR"
    assert result["audit_complete"] is False
    assert result["errors"][0]["type"] == "PermissionError"
    assert "original audit filesystem failure" in result["errors"][0]["message"]


def test_graph_failure_uses_memory_and_never_decodes_audit_with_locale(tmp_path, monkeypatch):
    import financial_filing_agent.services.pipeline as module
    instance = pipeline(tmp_path)
    class BrokenGraph:
        def invoke(self, state, config):
            instance.latest_state = {**state, "warnings": ["保留最新状态 — “quote”"]}
            raise PermissionError("original graph failure")
    monkeypatch.setattr(module, "build_graph", lambda nodes: BrokenGraph())
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        assert path.name != "audit.json", "Exception recovery must not reread the audit"
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    result = instance.run("Revenue FY2025 FY2024", "evaluation/fixtures/demo.html")
    assert result["final_status"] == "ERROR"
    assert result["warnings"] == ["保留最新状态 — “quote”"]
    assert result["errors"][0]["type"] == "PermissionError"


def test_audit_directory_denied_is_typed_error(tmp_path, monkeypatch):
    import financial_filing_agent.services.pipeline as module
    def denied(*args):
        raise PermissionError("cannot create audit directory")
    monkeypatch.setattr(module, "Audit", denied)
    result = pipeline(tmp_path).run("Revenue FY2025 FY2024", "evaluation/fixtures/demo.html")
    assert result["final_status"] == "ERROR"
    assert result["audit_path"] is None


def test_progress_start_precedes_work_and_completion_contains_observable_results(tmp_path):
    events = []
    result = pipeline(tmp_path).run("Revenue FY2025 FY2024", "evaluation/fixtures/demo.html", on_progress=events.append)
    assert result["final_status"] == "SUCCESS"
    assert len(events) >= 20
    assert events[0]["phase"] == "started"
    assert events[0]["node"] == "validate_request"
    assert [e["phase"] for e in events if e["node"] == "verify"] == ["started", "completed"]
    assert any(e["node"] == "verify" and "PASS" in e["detail"] for e in events)
    assert any(e["node"] == "calculate" and "10 percent" in e["detail"] for e in events)


@pytest.mark.skipif(os.name != "nt", reason="Real Windows sharing-mode regression")
def test_actual_windows_read_handle_blocks_replace_but_run_saves_recovery(tmp_path):
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    instance = pipeline(tmp_path)
    handles = []
    def lock(event):
        if event["node"] == "next_component" and event["phase"] == "started":
            handle = create(str((instance.audit.directory / "audit.json").resolve()),
                            0x80000000, 1, None, 3, 0x80, None)
            assert handle != wintypes.HANDLE(-1).value
            handles.append(handle)
    try:
        result = instance.run("Revenue FY2025 FY2024 — company’s 中文", "evaluation/fixtures/demo.html", on_progress=lock)
        assert handles
        assert result["final_status"] == "SUCCESS"
        assert "audit-recovery-" in result["audit_path"]
        assert json.loads(Path(result["audit_path"]).read_text(encoding="utf-8"))["state"]["final_status"] == "SUCCESS"
    finally:
        for handle in handles:
            kernel.CloseHandle(handle)
