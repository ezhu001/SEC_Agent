from pathlib import Path
import pytest
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.tools.filing_loader import load_filing
from financial_filing_agent.tools.filing_parser import parse_filing
from financial_filing_agent.tools.concept_validation import assess_concept, gross_profit_identity
from financial_filing_agent.retrieval.lexical_retriever import lexical_signals
from financial_filing_agent.retrieval.finbert_retriever import EmbeddingCache
from financial_filing_agent.services.progress import summary
from tests.test_metric_workflow import ConceptRetriever

SOURCE = Path("evaluation/fixtures/converted_apple_2026_10k.html")


class Decoder:
    version = {"name": "test-only-unit-confused-decoder"}
    def __init__(self, forbidden=False):
        self.calls = []
        self.forbidden = forbidden
    def complete(self, role, system, payload, schema):
        assert not self.forbidden, "No decoder calls permitted with Qwen OFF"
        self.calls.append({"role": role, "payload": payload})
        # Reproduce the original model misconception if it is asked to judge
        # gross_profit. A source identity certificate should prevent that call.
        gross = payload.get("required_component") == "gross_profit"
        from evaluation.review_double import review_checks
        return schema.model_validate({"verdict": "FAIL" if gross else "PASS", "checks": review_checks(payload),
            "error_type": "wrong_line_item" if gross else "none", "confidence": 0.9,
            "reason": "Gross margin is a percentage, not gross profit" if gross else "Revenue concept matches"})


def execute(tmp_path, enabled):
    decoder = Decoder(forbidden=not enabled)
    result = Pipeline(Settings(artifact_dir=tmp_path, qwen_enabled=enabled), decoder, ConceptRetriever()).run(
        "", str(SOURCE), ["FY2025", "FY2024"], formula_id="gross_margin_change")
    return result, decoder


@pytest.mark.parametrize("enabled", [True, False])
def test_monetary_gross_margin_is_gross_profit_in_both_modes(tmp_path, enabled):
    result, decoder = execute(tmp_path, enabled)
    assert result["final_status"] == "SUCCESS", result["warnings"]
    assert result["correction_count"] == 0
    gross = result["verification_results"]["gross_profit"][-1]
    assert gross["verdict"] == "PASS"
    assert gross["method"] == "deterministic_accounting_identity"
    assert all(c["passed"] for c in gross["accounting_identity"]["checks"])
    assert set(gross["accounting_identity"]["source_evidence_ids"]) == {"gross_profit", "revenue", "cost_of_sales"}
    expected = (195201 / 416161 - 180683 / 391035) * 100
    assert result["calculation_result"]["value"] == pytest.approx(expected, abs=1e-12)
    assert result["calculation_result"]["unit"] == "percentage points"
    assert [c["payload"]["required_component"] for c in decoder.calls] == (["revenue"] if enabled else [])
    assert result["decoder_call_count"] == (1 if enabled else 0)


def test_off_without_menu_does_not_call_planner(tmp_path):
    decoder = Decoder(forbidden=True)
    result = Pipeline(Settings(artifact_dir=tmp_path, qwen_enabled=False), decoder, ConceptRetriever()).run(
        "Gross margin change FY2025 FY2024", str(SOURCE))
    assert result["final_status"] == "NEEDS_INPUT"
    assert not decoder.calls


def test_percentage_row_cannot_be_used_as_gross_profit(tmp_path):
    filing, html = load_filing(str(SOURCE), Settings(artifact_dir=tmp_path))
    rows, _ = parse_filing(html, filing)
    row = next(r for r in rows if r.label == "Gross margin")
    for fact in row.facts:
        fact.unit = "percent"
        fact.currency = None
    concept = assess_concept(row, "gross_profit", ["FY2025", "FY2024"], filing.content_hash, {r.evidence_id for r in rows})
    assert concept["status"] == "FAIL"
    assert lexical_signals(row, "gross_profit")[1:] == (False, False)


def test_mismatch_cannot_be_certified(tmp_path):
    filing, html = load_filing(str(SOURCE), Settings(artifact_dir=tmp_path))
    rows, _ = parse_filing(html, filing)
    row = next(r for r in rows if r.label == "Gross margin")
    row.facts[1].value += 1_000_000
    assert gross_profit_identity(row, rows, ["FY2025", "FY2024"])["status"] == "MISMATCH"


def test_off_still_requires_missing_periods_and_all_components(tmp_path):
    decoder = Decoder(forbidden=True)
    result = Pipeline(Settings(artifact_dir=tmp_path, qwen_enabled=False), decoder, ConceptRetriever()).run(
        "", str(SOURCE), ["FY2025", "FY2024"], formula_id="current_ratio_change")
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["calculation_result"] is None
    assert not decoder.calls
