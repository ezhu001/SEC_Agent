from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.config.settings import Settings
from evaluation.doubles import ScriptedDecoder, DemoRetriever


@pytest.mark.parametrize("source,expected", [("demo.html", "10 percent"), ("converted_apple_2026_10k.html", "6.42551 percent")])
def test_streamlit_form_and_answer(tmp_path, monkeypatch, source, expected):
    real_run = Pipeline.run
    def run(self, question, source, periods=None, on_progress=None, **options):
        return real_run(Pipeline(self.settings.model_copy(update={"artifact_dir": tmp_path}), ScriptedDecoder(), DemoRetriever()), question, source, periods, on_progress=on_progress, **options)
    monkeypatch.setattr(Pipeline, "run", run)
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=30).run()
    assert not app.exception
    app.text_input[0].set_value(str((Path("evaluation/fixtures") / source).resolve()))
    app.text_area[0].set_value("Revenue growth FY2025 FY2024")
    next(b for b in app.button if b.label == "Run Analysis").click().run()
    assert not app.exception
    assert app.session_state["result"]["final_status"] == "SUCCESS"
    assert app.metric[0].value == expected
    completed = [e for e in app.session_state["execution_steps"] if e["phase"] == "completed"]
    assert [e["node"] for e in completed][:4] == ["validate_request", "load_filing", "plan_task", "build_evidence"]
    assert completed[-1]["node"] == "finish"
    if source.startswith("converted"):
        assert any("No USD denomination was assumed" in message.value for message in app.info)


def test_streamlit_audit_failure_displays_error_without_traceback(tmp_path, monkeypatch):
    from financial_filing_agent.services.audit import Audit
    real_run = Pipeline.run
    def run(self, question, source, periods=None, on_progress=None, **options):
        return real_run(Pipeline(self.settings.model_copy(update={"artifact_dir": tmp_path}), ScriptedDecoder(), DemoRetriever()),
                        question, source, periods, on_progress=on_progress, **options)
    def denied(*args, **kwargs):
        raise PermissionError("simulated audit lock — 中文")
    monkeypatch.setattr(Pipeline, "run", run)
    monkeypatch.setattr(Audit, "save", denied)
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=30).run()
    app.text_input[0].set_value(str(Path("evaluation/fixtures/demo.html").resolve()))
    app.text_area[0].set_value("Revenue growth FY2025 FY2024")
    next(b for b in app.button if b.label == "Run Analysis").click().run()
    assert not app.exception
    assert app.session_state["result"]["final_status"] == "ERROR"
    assert any("Audit persistence failed" in error.value for error in app.error)


def test_metric_menu_runs_both_ratio_components_without_planner(tmp_path, monkeypatch):
    from tests.test_metric_workflow import RoleDecoder, ConceptRetriever
    from evaluation.fixtures import APPLE_HTML
    real_run = Pipeline.run
    decoder = RoleDecoder()
    def run(self, question, source, periods=None, on_progress=None, **options):
        return real_run(Pipeline(self.settings.model_copy(update={"artifact_dir": tmp_path}), decoder, ConceptRetriever()), question, source, periods, on_progress, **options)

    monkeypatch.setattr(Pipeline, "run", run)
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=30).run()
    app.selectbox[0].select("current_ratio_change").run()
    assert any("current_assets, current_liabilities" in caption.value for caption in app.caption)
    app.text_input[0].set_value(str(APPLE_HTML.resolve()))
    app.text_input[1].set_value("FY2025 FY2024")
    next(b for b in app.button if b.label == "Run Analysis").click().run()
    assert not app.exception
    result = app.session_state["result"]
    assert result["final_status"] == "SUCCESS", result["errors"]
    assert set(result["accepted_evidence"]) == {"current_assets", "current_liabilities"}
    assert len(result["input_inventory"]) == 4
    assert all(call["role"] == "verifier" for call in decoder.calls)


def test_qwen_toggle_off_uses_rules_and_no_ollama_calls(tmp_path, monkeypatch):
    from tests.test_qwen_modes import Decoder, SOURCE
    from tests.test_metric_workflow import ConceptRetriever
    real_run = Pipeline.run
    decoder = Decoder(forbidden=True)
    def run(self, question, source, periods=None, on_progress=None, **options):
        return real_run(Pipeline(self.settings.model_copy(update={"artifact_dir": tmp_path}), decoder, ConceptRetriever()),
                        question, source, periods, on_progress, **options)
    monkeypatch.setattr(Pipeline, "run", run)
    app = AppTest.from_file(Path("app.py").resolve(), default_timeout=30).run()
    next(c for c in app.checkbox if c.label == "Enable Qwen agents").uncheck().run()
    assert next(b for b in app.button if b.label == "Check Ollama status").disabled
    app.selectbox[0].select("gross_margin_change").run()
    app.text_input[0].set_value(str(SOURCE.resolve()))
    app.text_input[1].set_value("FY2025 FY2024")
    next(b for b in app.button if b.label == "Run Analysis").click().run()
    assert not app.exception
    result = app.session_state["result"]
    assert result["final_status"] == "SUCCESS"
    assert result["config"]["qwen_enabled"] is False
    assert result["decoder_call_count"] == 0
    assert not decoder.calls
    assert any("disabled (deterministic rules only)" in c.value for c in app.caption)
