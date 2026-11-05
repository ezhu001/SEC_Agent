"""Regression for the user's converted Apple filing and missing currency metadata."""
import json
from pathlib import Path

import pytest
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.tools.filing_loader import load_filing
from financial_filing_agent.tools.filing_parser import parse_filing
from financial_filing_agent.tools.validation import compatible_inputs, guard, EvidenceError
from evaluation.doubles import ScriptedDecoder, DemoRetriever

SOURCE = Path("evaluation/fixtures/converted_apple_2026_10k.html")
QUESTION = "How did total revenue change from FY2024 to FY2025"


@pytest.fixture
def parsed(tmp_path):
    filing, html = load_filing(str(SOURCE), Settings(artifact_dir=tmp_path))
    return filing, parse_filing(html, filing)[0]


def test_converted_revenue_has_supported_monetary_basis(parsed):
    filing, rows = parsed
    assert filing.metadata["entity"] == "Apple Inc."
    assert filing.metadata["form"] == "10-K"
    row = next(r for r in rows if r.label == "Total net sales")
    assert [f.period for f in row.facts] == ["FY2026", "FY2025", "FY2024"]
    assert [f.value for f in row.facts] == [478834e6, 416161e6, 391035e6]
    assert all(f.unit == "currency" and f.currency is None and f.unit_basis for f in row.facts)
    assert guard(row, "revenue", ["FY2025", "FY2024"], filing.content_hash, row.evidence_id, {r.evidence_id for r in rows})["passed"]


def test_user_question_succeeds_with_cold_and_warm_cache(tmp_path):
    settings = Settings(artifact_dir=tmp_path)
    for _ in range(2):
        result = Pipeline(settings, ScriptedDecoder(), DemoRetriever()).run(QUESTION, str(SOURCE))
        assert result["final_status"] == "SUCCESS", result["warnings"]
        assert result["calculation_result"]["value"] == pytest.approx(6.425511782832739)
        assert result["correction_count"] == 0
        assert len(result["verification_results"]["revenue"]) == 1
        assert "No USD denomination was assumed" in result["warnings"][-1]
        assert result["config"]["parser_version"] == "ixbrl-table-v5"


def test_unknown_currency_cannot_cross_source_bases(parsed):
    _, rows = parsed
    revenue = next(r for r in rows if r.label == "Total net sales")
    other = revenue.model_copy(deep=True)
    for fact in other.facts:
        fact.unit_basis = "different-filing-or-table"
    with pytest.raises(EvidenceError, match="common monetary source"):
        compatible_inputs({"revenue": revenue, "other": other}, ["FY2025", "FY2024"])


def test_currency_cancellation_is_explicitly_limited_to_dimensionless_results(parsed):
    _, rows = parsed
    revenue = next(r for r in rows if r.label == "Total net sales")
    with pytest.raises(EvidenceError, match="dimensional monetary result"):
        compatible_inputs({"revenue": revenue}, ["FY2025", "FY2024"])
    compatible_inputs({"revenue": revenue}, ["FY2025", "FY2024"], allow_currency_cancellation=True)


def test_unknown_currency_cannot_mix_with_identified_currency(parsed):
    _, rows = parsed
    revenue = next(r for r in rows if r.label == "Total net sales")
    revenue.facts[1].currency = "USD"
    with pytest.raises(EvidenceError, match="Mixed currencies"):
        compatible_inputs({"revenue": revenue}, ["FY2025", "FY2024"])


def test_dollar_sign_does_not_mean_usd():
    from financial_filing_agent.schemas.evidence import Filing
    source = '''<p>Consolidated statements in millions</p><table>
    <tr><th>Line item</th><th>2025</th><th>2024</th></tr>
    <tr><td>Net sales</td><td>$110</td><td>$100</td></tr>
    <tr><td>Operating income</td><td>30</td><td>20</td></tr></table>'''
    rows, _ = parse_filing(source, Filing(source="synthetic", content_hash="f", local_path="test"))
    assert rows[0].facts[0].unit == "currency"
    assert rows[0].facts[0].currency is None


def test_guard_failures_do_not_reverify_same_unchanged_row(tmp_path):
    source = tmp_path / "no-units.html"
    source.write_text(Path("evaluation/fixtures/demo.html").read_text().replace("in USD", ""))
    result = Pipeline(Settings(artifact_dir=tmp_path / "runs"), ScriptedDecoder(), DemoRetriever()).run(QUESTION, str(source))
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    guarded = [r["evidence_id"] for r in result["guard_results"]["revenue"]]
    assert len(guarded) == len(set(guarded))
    assert any("known_units" in w for w in result["warnings"])
