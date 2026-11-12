import pytest

from financial_filing_agent.config.formulas import registered_plan
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.schemas.evidence import EvidenceRow, Fact
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.tools.validation import guard
from evaluation.doubles import DemoRetriever, ScriptedDecoder


PERIODS = ["FY2025", "FY2024"]


@pytest.fixture
def pipeline(tmp_path):
    return Pipeline(Settings(artifact_dir=tmp_path), ScriptedDecoder(), DemoRetriever())


def source_row(values=(110, 100)):
    return EvidenceRow(evidence_id="selected", filing_hash="filing", source="test", statement="operations",
        table=0, row=1, label="Total net sales", text="Total net sales",
        facts=[Fact(period=p, value=value, raw_value=str(value), unit="currency", currency="USD", cell=i)
               for i, (p, value) in enumerate(zip(PERIODS, values))])


def state_for(row, formula="revenue_growth", component="revenue", records=None):
    return {"active_component": component, "proposed_id": row.evidence_id,
        "formula_id": formula, "required_periods": PERIODS,
        "task_plan": registered_plan(formula, PERIODS).model_dump(mode="json"),
        "verification_results": {component: records or [{"evidence_id": row.evidence_id, "verdict": "PASS"}]},
        "accepted_evidence": {}, "guard_results": {}, "correction_attempts": 0, "warnings": []}


def test_acceptance_does_not_repeat_structural_eligibility(monkeypatch):
    def unexpected_eligibility(*args, **kwargs):
        pytest.fail("Acceptance must rely on the eligibility check before verification")
    monkeypatch.setattr("financial_filing_agent.tools.validation.eligibility", unexpected_eligibility)
    row = source_row()
    assert guard(row, row.evidence_id, ["FY2024"])["checks"] == {
        "reverified_selection": True, "nonzero_denominator": True}


@pytest.mark.parametrize("latest", [
    {"evidence_id": "other-selection", "verdict": "PASS"},
    {"evidence_id": "selected", "verdict": "FAIL"},
    {"evidence_id": "selected", "verdict": "UNCERTAIN"},
])
def test_replacement_or_later_rejection_cannot_reuse_an_earlier_pass(pipeline, latest):
    row = source_row()
    pipeline.rows = lambda state: [row]
    state = state_for(row, records=[{"evidence_id": row.evidence_id, "verdict": "PASS"}, latest])
    result = pipeline.guarding(state)
    assert result["route"] == "correct"
    assert not result.get("accepted_evidence")
    assert not result["guard_results"]["revenue"][-1]["checks"]["reverified_selection"]


@pytest.mark.parametrize("formula,component,values,passed", [
    ("revenue_growth", "revenue", (0, 100), True),
    ("revenue_growth", "revenue", (110, 0), False),
    ("current_ratio_change", "current_assets", (0, 0), True),
    ("current_ratio_change", "current_liabilities", (100, 0), False),
    ("current_ratio_change", "current_liabilities", (0, 100), False),
    ("current_ratio_change", "current_liabilities", (100, 100), True),
])
def test_denominator_policy_at_acceptance(pipeline, formula, component, values, passed):
    row = source_row(values)
    pipeline.rows = lambda state: [row]
    result = pipeline.guarding(state_for(row, formula, component))
    record = result["guard_results"][component][-1]
    assert record["passed"] is passed
    assert result["route"] == ("next_component" if passed else "correct")
    assert bool(result.get("accepted_evidence")) is passed


def test_missing_denominator_is_not_accepted_as_nonzero():
    row = source_row()
    row.facts = row.facts[:1]
    assert not guard(row, row.evidence_id, ["FY2024"])["passed"]


@pytest.mark.parametrize("verified_id,success", [("selected", True), ("other-selection", False)])
def test_calculator_keeps_verified_id_check_without_repeating_guard(pipeline, monkeypatch, verified_id, success):
    def unexpected_guard(*args, **kwargs):
        pytest.fail("The calculator must not repeat the acceptance guard")
    monkeypatch.setattr("financial_filing_agent.services.pipeline.guard", unexpected_guard)
    row = source_row()
    pipeline.rows = lambda state: [row]
    state = state_for(row, records=[{"evidence_id": verified_id, "verdict": "PASS"}])
    state["accepted_evidence"] = {"revenue": row.evidence_id}
    result = pipeline.calculation(state)
    if success:
        assert result["final_status"] == "SUCCESS"
        assert result["calculation_result"]["value"] == 10
    else:
        assert result["route"] == "correct"
        assert not result["accepted_evidence"]
        assert any("not verified after selection" in warning for warning in result["warnings"])
