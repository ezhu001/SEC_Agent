from pathlib import Path
import pytest
from financial_filing_agent.config.formulas import registered_plan
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.retrieval.lexical_retriever import lexical_signals
from financial_filing_agent.config.financial_concepts import CONCEPTS
from financial_filing_agent.retrieval.sufficiency import assess
from evaluation.fixtures import APPLE_HTML


class RoleDecoder:
    version = {"name": "test-decision-double"}
    def __init__(self):
        self.calls = []
    def complete(self, role, system, payload, schema):
        self.calls.append({"role": role, "payload": payload})
        assert role == "verifier", "Menu tasks must not call a model planner or calculator"
        expected = {"current_assets": "Total current assets", "current_liabilities": "Total current liabilities"}
        good = payload["proposed_evidence"]["label"] == expected[payload["required_component"]]
        answer = {"verdict": "PASS" if good else "FAIL", "error_type": "none" if good else "wrong_line_item",
                                      "confidence": 0.9, "reason": "Test-only accounting concept decision", "findings": [] if good else
                                      [{"check": "concept_match", "evidence_field": "label", "evidence_quote": payload["proposed_evidence"]["label"], "reason": "Different accounting concept"}]}
        from evaluation.review_double import review_checks
        answer["checks"] = review_checks(payload, answer["findings"])
        return schema.model_validate(answer)


class ConceptRetriever:
    def rank(self, rows, component, periods, query):
        ranked = []
        for row in rows:
            lexical, exact, xbrl = lexical_signals(row, component)
            ranked.append({"evidence_id": row.evidence_id, "label": row.label, "fusion_score": lexical,
                "signals": {"statement": row.statement == CONCEPTS[component][0],
                    "periods": all(sum(f.period == p for f in row.facts) == 1 for p in periods),
                    "numeric": bool(row.facts), "exact_label": exact, "xbrl": xbrl, "lexical": lexical}})
        return sorted(ranked, key=lambda r: -r["fusion_score"]), {"candidate_count": len(ranked)}


def execute(tmp_path, source, **options):
    decoder = RoleDecoder()
    result = Pipeline(Settings(artifact_dir=tmp_path), decoder, ConceptRetriever()).run("", str(source),
        ["FY2025", "FY2024"], formula_id="current_ratio_change", **options)
    return result, decoder


def test_all_components_verified_before_single_deterministic_calculation(tmp_path):
    result, decoder = execute(tmp_path, APPLE_HTML)
    assert result["final_status"] == "SUCCESS", result["warnings"]
    assert [c["payload"]["required_component"] for c in decoder.calls] == ["current_assets", "current_liabilities"]
    assert len(result["input_inventory"]) == 4
    assert all(c["status"] == "FOUND" for c in result["input_inventory"])
    nodes = [e["node"] for e in result["audit_events"]]
    assert nodes.count("guard") == 2 and nodes.count("calculate") == 1
    assert nodes.index("calculate") > max(i for i, n in enumerate(nodes) if n == "guard")
    calc = result["calculation_result"]
    assert calc["value"] == pytest.approx(0.025980345684583517, abs=1e-12)
    assert calc["comparison"]["absolute_change"] == calc["value"]
    assert calc["comparison"]["new_value"] == calc["intermediates"]["FY2025"]
    assert calc["comparison"]["old_value"] == calc["intermediates"]["FY2024"]
    assert calc["comparison"]["direction"] == "increase"
    assert calc["comparison"]["absolute_change_unit"] == "ratio units"


def test_2026_filing_missing_2024_balances_stops_before_models(tmp_path):
    source = Path("evaluation/fixtures/converted_apple_2026_10k.html")
    result, decoder = execute(tmp_path, source)
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert not decoder.calls
    missing = [c for c in result["input_inventory"] if c["status"] == "MISSING_PERIOD"]
    assert {(c["component"], c["period"]) for c in missing} == {("current_assets", "FY2024"), ("current_liabilities", "FY2024")}
    assert result["calculation_result"] is None
    assert not result["guard_results"]


def test_explicit_supporting_filing_supplies_complete_inputs_with_provenance(tmp_path):
    source = Path("evaluation/fixtures/converted_apple_2026_10k.html")
    result, decoder = execute(tmp_path, source, supplementary_sources=[str(APPLE_HTML)])
    assert result["final_status"] == "SUCCESS", result["warnings"]
    assert result["requested_filing_source"] == str(source)
    assert result["filing_source"] == str(APPLE_HTML)
    assert result["calculation_result"]["value"] == pytest.approx(0.025980345684583517)
    assert any(e["node"] == "supporting_filing_search" for e in result["audit_events"])


def test_menu_plan_has_fixed_formula_dependencies_and_tool():
    plan = registered_plan("current_ratio_change", ["FY2024", "FY2025"])
    assert plan.required_components == ["current_assets", "current_liabilities"]
    assert plan.required_periods == ["FY2025", "FY2024"]
    assert plan.calculation_tool == "registered_python_calculator"
    assert plan.comparison_policy == "python_only"
    assert registered_plan("current_ratio_change", None).status == "NEEDS_INPUT"


def test_opted_in_cache_search_finds_complete_same_company_source(tmp_path):
    from financial_filing_agent.tools.filing_loader import load_filing
    load_filing(str(APPLE_HTML), Settings(artifact_dir=tmp_path))
    result, _ = execute(tmp_path, "evaluation/fixtures/converted_apple_2026_10k.html", use_cached_filings=True)
    assert result["final_status"] == "SUCCESS"
    assert result["filing_hash"] != Path(result["requested_filing_source"]).stem
    assert Path(result["evidence_artifact_reference"]).name == "evidence-supporting.json"
    assert Path(result["audit_path"]).with_name("evidence.json").is_file()


def test_supporting_filing_from_another_company_is_not_used(tmp_path):
    other = tmp_path / "other.html"
    other.write_text(APPLE_HTML.read_text(encoding="utf-8").replace("Apple Inc.", "Unrelated Company"), encoding="utf-8")
    result, decoder = execute(tmp_path / "runs", "evaluation/fixtures/converted_apple_2026_10k.html", supplementary_sources=[str(other)])
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert not decoder.calls


def test_sufficiency_cannot_borrow_periods_from_a_different_candidate():
    def row(periods, exact):
        return {"signals": {"statement": True, "periods": periods, "numeric": True, "exact_label": exact, "xbrl": False}}
    assert assess([row(False, True), row(True, False)])["status"] == "INSUFFICIENT"
