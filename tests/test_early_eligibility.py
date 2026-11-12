import json
from pathlib import Path

import pytest

from financial_filing_agent.config.settings import Settings
from financial_filing_agent.schemas.evidence import EvidenceRow, Fact, SourceText
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.tools.validation import eligibility, guard
from evaluation.doubles import DemoRetriever, ScriptedDecoder


PERIODS = ["FY2025", "FY2024"]


def revenue_row(evidence_id="valid", label="Total net sales"):
    return EvidenceRow(evidence_id=evidence_id, filing_hash="filing", source="test", statement="operations",
        table=0, row=1, label=label, text=label, nearby_context="Consolidated Statements of Operations in USD",
        statement_heading=SourceText(text="Consolidated Statements of Operations", locator="demo:heading", filing_hash="filing"),
        facts=[Fact(period=p, value=value, raw_value=str(value), unit="currency", currency="USD", cell=i)
               for i, (p, value) in enumerate(zip(PERIODS, [110, 100]))])


@pytest.mark.parametrize("change,check", [
    ({"unit": "percent"}, "known_units"),
    ({"unit": None, "currency": None}, "known_units"),
    ({"dimensions": {"ProductAxis": "ProductMember"}}, "consolidated"),
    ({"instant": True}, "period_kind"),
    ({"start": "2025-07-01", "end": "2025-09-30"}, "annual_duration"),
    ({"currency": "EUR"}, "compatible_currency"),
    ({"period": "FY2023"}, "unique_requested_periods"),
    ({"value": float("nan")}, "finite_values"),
])
def test_incompatible_facts_fail_before_verification(change, check):
    row = revenue_row()
    row.facts[0] = row.facts[0].model_copy(update=change)
    result = eligibility(row, "revenue", PERIODS, "filing", {row.evidence_id})
    assert not result["passed"]
    assert not result["checks"][check]


def test_duplicate_periods_and_wrong_source_are_ineligible():
    row = revenue_row()
    row.facts.append(row.facts[0].model_copy())
    result = eligibility(row, "revenue", PERIODS, "other-filing", set())
    assert not result["checks"]["unique_requested_periods"]
    assert not result["checks"]["source_membership"]


def test_monetary_basis_is_preserved_and_final_guard_still_requires_verification():
    row = revenue_row()
    for fact in row.facts:
        fact.currency = None
        fact.unit_basis = "filing:table:0:monetary"
    assert eligibility(row, "revenue", PERIODS, "filing", {row.evidence_id})["passed"]
    assert not guard(row, None)["passed"]
    assert guard(row, row.evidence_id)["passed"]


class SpyRetriever(DemoRetriever):
    def __init__(self, scenario="success"):
        super().__init__(scenario)
        self.pools = []

    def rank(self, rows, component, periods, query):
        self.pools.append([row.evidence_id for row in rows])
        assert "invalid" not in self.pools[-1], "Invalid evidence must never reach embedding/ranking"
        return super().rank(rows, component, periods, query)


def install_rows(monkeypatch, rows):
    def parse(html, filing):
        rebound = [r.model_copy(update={"filing_hash": filing.content_hash}, deep=True) for r in rows]
        for row in rebound:
            if row.statement_heading:
                row.statement_heading.filing_hash = filing.content_hash
        return rebound, []
    monkeypatch.setattr("financial_filing_agent.services.pipeline.parse_filing", parse)


@pytest.mark.parametrize("top_k", [1, 5])
def test_invalid_rows_stay_out_of_retrieval_expansion_and_recovery(tmp_path, monkeypatch, top_k):
    invalid = revenue_row("invalid")
    invalid.facts[0].dimensions = {"SegmentAxis": "Consumer"}
    install_rows(monkeypatch, [invalid, revenue_row(), revenue_row("cost", "Total cost of sales")])
    retriever = SpyRetriever("recovery")
    decoder = ScriptedDecoder("recovery")
    result = Pipeline(Settings(artifact_dir=tmp_path, qwen_enabled=True, top_k=top_k), decoder, retriever).run(
        "", "evaluation/fixtures/demo.html", PERIODS, formula_id="revenue_growth")
    assert result["final_status"] == "SUCCESS", result["errors"]
    assert result["accepted_evidence"] == {"revenue": "valid"}
    assert result["calculation_result"]["value"] == 10
    assert result["correction_count"] > 0
    assert result["expanded_search_count"] == 1
    assert len(retriever.pools) == 2
    for call in decoder.calls:
        payload = call["request"]
        if call["role"] == "verifier":
            assert payload["proposed_evidence"]["evidence_id"] != "invalid"
        elif call["role"] == "corrector":
            assert all(r["evidence_id"] != "invalid" for r in payload["available_candidates"])
    for diagnostic in result["retrieval_diagnostics"]["revenue"]:
        excluded = diagnostic["eligibility"]["rejected"]
        assert excluded[0]["evidence_id"] == "invalid"
        assert not excluded[0]["checks"]["consolidated"]
    saved = json.loads(Path(result["evidence_artifact_reference"]).read_text())
    assert "invalid" in {r["evidence_id"] for r in saved}, "Filtering must preserve original audit evidence"


@pytest.mark.parametrize("change,check", [
    ({"unit": "percent"}, "known_units"),
    ({"dimensions": {"SegmentAxis": "Consumer"}}, "consolidated"),
])
def test_empty_eligible_pool_stops_before_retrieval_or_qwen(tmp_path, monkeypatch, change, check):
    invalid = revenue_row("invalid")
    invalid.facts[0] = invalid.facts[0].model_copy(update=change)
    install_rows(monkeypatch, [invalid])
    retriever, decoder = SpyRetriever(), ScriptedDecoder()
    result = Pipeline(Settings(artifact_dir=tmp_path, qwen_enabled=True), decoder, retriever).run(
        "", "evaluation/fixtures/demo.html", PERIODS, formula_id="revenue_growth")
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert not retriever.pools and not decoder.calls
    assert not result["verification_results"] and not result["guard_results"]
    assert result["calculation_result"] is None
    assert result["expanded_search_count"] == result["correction_count"] == 0
    assert any(check in warning for warning in result["warnings"])


def test_invalid_replacement_is_rechecked_before_verification(tmp_path):
    invalid = revenue_row("invalid")
    invalid.facts[0].unit = "percent"
    decoder = ScriptedDecoder()
    pipeline = Pipeline(Settings(artifact_dir=tmp_path, qwen_enabled=True), decoder, SpyRetriever())
    pipeline.rows = lambda state: [invalid]
    state = {"proposed_id": "invalid", "active_component": "revenue", "required_periods": PERIODS,
             "filing_hash": "filing", "correction_attempts": 0, "guard_results": {}, "warnings": []}
    result = pipeline.verification(state)
    assert not decoder.calls
    assert result["route"] == "correct"
    assert not result["guard_results"]["revenue"][0]["checks"]["known_units"]
