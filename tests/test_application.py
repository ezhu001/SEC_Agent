import json
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.schemas.evidence import Filing, EvidenceRow, Fact
from financial_filing_agent.schemas.results import Verification, Correction
from financial_filing_agent.schemas.task import TaskPlan
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.tools.filing_loader import load_filing
from financial_filing_agent.tools.filing_parser import parse_filing
from financial_filing_agent.tools.numeric_parser import number
from financial_filing_agent.tools.validation import guard, EvidenceError
from financial_filing_agent.tools.calculator import calculate
from financial_filing_agent.agents.corrector import correct
from financial_filing_agent.agents.planner import plan_task
from financial_filing_agent.models.local_decoder import OllamaDecoder, DecoderError
from financial_filing_agent.retrieval.sufficiency import assess
from evaluation.doubles import ScriptedDecoder, DemoRetriever, task
from evaluation.fixtures import APPLE_HTML, DEVELOPMENT_REFERENCES

DEMO = Path("evaluation/fixtures/demo.html")


def run(tmp_path, scenario="success", source=DEMO, question=None, decoder=None, **kwargs):
    settings = Settings(artifact_dir=tmp_path, **kwargs)
    question = question or ("Inventory growth FY2025 FY2024" if scenario == "missing" else "Revenue growth FY2025 FY2024")
    return Pipeline(settings, decoder or ScriptedDecoder(scenario), DemoRetriever(scenario)).run(question, str(source))


@pytest.mark.parametrize("scenario,expected", [("success", "SUCCESS"), ("recovery", "SUCCESS"), ("missing", "INSUFFICIENT_EVIDENCE")])
def test_graph_demonstrations(tmp_path, scenario, expected):
    result = run(tmp_path, scenario)
    assert result["final_status"] == expected
    assert Path(result["audit_path"]).is_file()
    artifact = json.loads(Path(result["audit_path"]).read_text())
    assert artifact["state"]["config_hash"]
    assert artifact["state"]["audit_events"][-1]["node"] == "finish"
    if expected == "SUCCESS":
        assert result["calculation_result"]["value"] == 10
    else:
        assert result["calculation_result"] is None
        assert "calculate" not in [e["node"] for e in result["audit_events"]]
        assert result["expanded_search_count"] == 0  # Missing statement-period cells stop at preflight.
        assert not result["verification_results"]
    if scenario == "recovery":
        records = result["verification_results"]["revenue"]
        assert [r["verdict"] for r in records] == ["FAIL", "PASS"]
        assert records[0]["evidence_id"] != records[1]["evidence_id"]
        assert result["correction_count"] == 1


def test_no_gold_in_runtime(tmp_path):
    result = run(tmp_path)
    text = json.dumps(result)
    for forbidden in ("gold_aliases", "is_gold_line_item", "expected_value", "derived_claim_correct", "tolerance"):
        assert forbidden not in text


class RefusesCorrection(ScriptedDecoder):
    def complete(self, role, system, payload, schema):
        if role == "corrector":
            self.calls.append({"role": role})
            return Correction(decision="NO_VALID_EVIDENCE", evidence_id=None, confidence=0.9, reason="No evidence")
        return super().complete(role, system, payload, schema)


def test_rejected_baseline_never_restored(tmp_path):
    result = run(tmp_path, "recovery", decoder=RefusesCorrection())
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert not result["accepted_evidence"]
    assert result["calculation_result"] is None


def test_correction_budget_zero(tmp_path):
    result = run(tmp_path, "recovery", correction_budget=0)
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["correction_count"] == 0


def test_guard_failure_blocks_calculation(tmp_path):
    html = DEMO.read_text().replace("in USD", "")
    path = tmp_path / "unknown-units.html"
    path.write_text(html)
    result = run(tmp_path / "artifacts", source=path)
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["calculation_result"] is None
    assert not result["guard_results"]["revenue"][0]["passed"]


def test_missing_period_abstains(tmp_path):
    path = tmp_path / "one-year.html"
    path.write_text(DEMO.read_text().replace("2024", "2023"))
    result = run(tmp_path / "artifacts", source=path)
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert not result["verification_results"]


@pytest.mark.parametrize("value,expected", [("(321)", -321), ("$1,234", 1234), ("0", 0), ("2.5", 2.5), ("2025", 2025), ("—", 0), ("label", None)])
def test_numeric_cells(value, expected):
    assert number(value) == expected


def test_parser_provenance_equal_values(tmp_path):
    f, html = load_filing(str(DEMO), Settings(artifact_dir=tmp_path))
    rows, _ = parse_filing(html.replace("110", "100"), f)
    row = rows[0]
    assert row.filing_hash == f.content_hash
    assert row.table == 0 and row.row == 1
    assert [(v.period, v.value) for v in row.facts] == [("FY2025", 100), ("FY2024", 100)]
    assert row.facts[0].cell == 1


@pytest.fixture(scope="module")
def apple_rows(tmp_path_factory):
    settings = Settings(artifact_dir=tmp_path_factory.mktemp("apple"))
    filing, html = load_filing(str(APPLE_HTML), settings)
    return filing, parse_filing(html, filing)[0]


@pytest.mark.parametrize("formula", list(DEVELOPMENT_REFERENCES))
def test_apple_development_calculation_regression(apple_rows, formula):
    filing, rows = apple_rows
    plan = task(formula)
    labels = {"revenue": "Total net sales", "operating_income": "Operating income", "current_assets": "Total current assets", "current_liabilities": "Total current liabilities"}
    accepted = {c: next(r for r in rows if r.label == labels[c]) for c in plan.required_components}
    for c, row in accepted.items():
        assert guard(row, c, plan.required_periods, filing.content_hash, row.evidence_id, {r.evidence_id for r in rows})["passed"]
    result = calculate(plan, accepted, {c: r.evidence_id for c, r in accepted.items()})
    expected, _ = DEVELOPMENT_REFERENCES[formula]
    assert result.value == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize("formula,expected", [("revenue_growth", 100), ("operating_margin", 50), ("operating_margin_change", 0), ("current_ratio", 0.5), ("current_ratio_change", 0), ("gross_margin", 50), ("gross_margin_change", 0), ("rd_intensity", 50), ("inventory_growth", 100), ("accounts_receivable_growth", 100)])
def test_registered_formulas(formula, expected):
    plan = task(formula)
    accepted = {}
    for i, c in enumerate(plan.required_components):
        accepted[c] = EvidenceRow(evidence_id=c, filing_hash="f", source="test", statement=plan.expected_statement_types[c], table=0, row=i, label=c, text=c,
            facts=[Fact(period=p, value=(100 if i == 0 else 200) / (j+1), raw_value="test", unit="currency", currency="USD", cell=j) for j, p in enumerate(plan.required_periods)])
    result = calculate(plan, accepted, {c: c for c in accepted})
    assert result.value == expected


def test_zero_denominator_and_mixed_units():
    plan = task()
    row = EvidenceRow(evidence_id="r", filing_hash="f", source="test", statement="operations", table=0, row=0, label="revenue", text="row",
        facts=[Fact(period="FY2025", value=10, raw_value="10", unit="currency", currency="USD", cell=1), Fact(period="FY2024", value=0, raw_value="0", unit="currency", currency="USD", cell=2)])
    with pytest.raises(EvidenceError, match="zero denominator"):
        calculate(plan, {"revenue": row}, {"revenue": "r"})
    row.facts[1].currency = "EUR"
    with pytest.raises(EvidenceError, match="Mixed currencies"):
        calculate(plan, {"revenue": row}, {"revenue": "r"})
    with pytest.raises(EvidenceError, match="Not all"):
        calculate(plan, {}, {})


@pytest.mark.parametrize("status", ["NEEDS_INPUT", "UNSUPPORTED_TASK"])
def test_planner_nonanswer(tmp_path, status):
    class Decoder(ScriptedDecoder):
        def complete(self, role, system, payload, schema):
            return TaskPlan(status=status, notes="Explicit non-answer")
    result = run(tmp_path, decoder=Decoder())
    assert result["final_status"] == status
    assert not result["retrieval_results"]


def test_planner_cannot_invent_periods():
    plan = plan_task(ScriptedDecoder(), "How did revenue change?", {})
    assert plan.status == "NEEDS_INPUT"


def test_contract_rejects_unknown_formula():
    with pytest.raises(ValidationError):
        TaskPlan(status="READY", formula_id="invented")
    with pytest.raises(ValidationError):
        Verification(verdict="PASS", error_type="wrong_line_item", confidence=2, reason="bad")


def test_corrector_rejects_hallucinated_id():
    class Decoder:
        def complete(self, *args):
            return Correction(decision="REPLACE", evidence_id="invented", confidence=0.8, reason="bad")
    with pytest.raises(DecoderError, match="outside"):
        correct(Decoder(), {"available_candidates": [{"evidence_id": "real"}]})


def test_ollama_unavailable_is_operational_error(tmp_path, monkeypatch):
    import requests
    def fail(*args, **kwargs):
        raise requests.ConnectionError("not running")
    monkeypatch.setattr(requests, "post", fail)
    decoder = OllamaDecoder(Settings(transport_retries=0))
    result = run(tmp_path, decoder=decoder)
    assert result["final_status"] == "ERROR"
    assert result["errors"][0]["type"] == "DecoderError"


def test_malformed_output_is_operational_error(tmp_path, monkeypatch):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"message": {"content": "not JSON"}}
    monkeypatch.setattr("requests.post", lambda *a, **k: Response())
    result = run(tmp_path, decoder=OllamaDecoder(Settings(transport_retries=0)))
    assert result["final_status"] == "ERROR"


def test_load_error_is_not_insufficient(tmp_path):
    result = run(tmp_path, source=tmp_path / "does-not-exist.html")
    assert result["final_status"] == "ERROR"


def test_fresh_process_cli():
    result = subprocess.run([sys.executable, "-m", "financial_filing_agent.cli", "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "--source" in result.stdout


def test_fresh_process_demo():
    result = subprocess.run([sys.executable, "-m", "evaluation.runner"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "INSUFFICIENT_EVIDENCE" in result.stdout
