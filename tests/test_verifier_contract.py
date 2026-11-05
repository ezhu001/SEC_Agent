import pytest
from pydantic import ValidationError
from financial_filing_agent.agents.verifier import verify
from financial_filing_agent.agents.verification_contract import VerifierContractError, build_contract
from financial_filing_agent.config.financial_concepts import definition
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.schemas.results import Verification, Correction
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.agents.corrector import correct
from tests.test_metric_workflow import ConceptRetriever


def payload(component="revenue"):
    return {"required_component": component, "formula_id": "rd_intensity", "required_periods": ["FY2025"],
        "expected_statement": "operations", "concept_definition": definition(component),
        "deterministic_concept_assessment": {"status": "PASS"},
        "proposed_evidence": {"evidence_id": "r", "label": "Total net sales", "statement": "operations",
            "nearby_context": "CONSOLIDATED STATEMENTS OF OPERATIONS (In millions)",
            "facts": [{"period": "FY2025", "value": 416161e6, "unit": "currency", "currency": "USD"}]},
        "accounting_identity": {"status": "UNAVAILABLE"}}


def good(request):
    from evaluation.review_double import review_checks
    return {"verdict": "PASS", "error_type": "none", "confidence": 0.9, "reason": "Registered revenue label with correct source scope", "findings": [], "checks": review_checks(request)}


def invented_requirement(request):
    finding = {"check": "reporting_scope", "evidence_field": "nearby_context",
               "evidence_quote": request["proposed_evidence"]["nearby_context"], "reason": "Missing required accounting identity certificate"}
    return {"verdict": "UNCERTAIN", "error_type": "insufficient_evidence", "confidence": 0.9,
        "checks": [{**finding, "status": "UNCERTAIN"}],
        "reason": "The accounting identity is UNAVAILABLE; a certificate is required for revenue",
        "findings": [finding]}


class ConfusedDecoder:
    version = {"name": "contract-regression-double"}
    def __init__(self, repair=False):
        self.calls, self.repair = [], repair
    def complete(self, role, system, request, schema):
        self.calls.append({"role": role, "request": request.copy()})
        assert role == "verifier", "An invalid review must never trigger a corrector"
        if request["required_component"] != "revenue" or (self.repair and "contract_feedback" in request):
            return schema.model_validate(good(request))
        return schema.model_validate(invented_requirement(request))


def test_contract_is_explicit_and_does_not_require_other_formula_components():
    contract = build_contract(payload())
    assert set(contract["resolved_by_python"]) == {"concept_match", "statement_match", "required_periods", "monetary_unit", "formula_role"}
    assert contract["open_checks"] == ["reporting_scope"]
    assert "NONE" in contract["certificate_requirement"]


def test_unavailable_optional_certificate_is_omitted_and_one_repair_is_bounded():
    decoder = ConfusedDecoder(repair=True)
    request = payload()
    request["alternatives"] = [{"label": "Distracting other row"}]
    result = verify(decoder, request)
    assert result.verdict == "PASS"
    assert len(decoder.calls) == 2
    assert all("accounting_identity" not in c["request"] for c in decoder.calls)
    assert all("alternatives" not in c["request"] for c in decoder.calls)
    assert decoder.calls[0]["contract_validation"]["passed"] is False
    assert decoder.calls[1]["contract_validation"]["passed"] is True


def test_persistent_invented_requirement_is_contract_error_not_missing_evidence():
    decoder = ConfusedDecoder()
    with pytest.raises(VerifierContractError, match="Optional Python"):
        verify(decoder, payload())
    assert len(decoder.calls) == 2


def test_invented_verifier_requirements_cannot_trigger_retrieval_expansion(tmp_path):
    result = Pipeline(Settings(artifact_dir=tmp_path), ConfusedDecoder(), ConceptRetriever()).run(
        "", "evaluation/fixtures/converted_apple_2026_10k.html", ["FY2025"], formula_id="rd_intensity")
    assert result["final_status"] == "ERROR"
    assert result["errors"][0]["type"] == "VerifierContractError"
    assert result["expanded_search_count"] == 0
    assert result["correction_count"] == 0
    assert result["calculation_result"] is None


def test_repaired_rd_review_completes_without_recovery(tmp_path):
    decoder = ConfusedDecoder(repair=True)
    result = Pipeline(Settings(artifact_dir=tmp_path), decoder, ConceptRetriever()).run(
        "", "evaluation/fixtures/converted_apple_2026_10k.html", ["FY2025"], formula_id="rd_intensity")
    assert result["final_status"] == "SUCCESS"
    assert result["calculation_result"]["value"] == pytest.approx(34550 / 416161 * 100)
    assert result["expanded_search_count"] == result["correction_count"] == 0


def test_no_source_grounded_finding_is_not_a_valid_negative_verdict():
    with pytest.raises(ValidationError, match="source-grounded"):
        Verification(verdict="UNCERTAIN", error_type="insufficient_evidence", confidence=0.8, reason="Need more checks", checks=[])


def test_resolved_alias_cannot_be_rejected_by_literal_name():
    class Decoder:
        calls = []
        def complete(self, role, system, request, schema):
            return schema.model_validate({"verdict": "FAIL", "error_type": "wrong_line_item", "confidence": 0.9,
                "checks": [],
                "reason": "Total net sales differs from canonical revenue", "findings": [{"check": "concept_match",
                    "evidence_field": "label", "evidence_quote": "Total net sales", "reason": "Names differ"}]})
    with pytest.raises((VerifierContractError, ValidationError)):
        verify(Decoder(), payload())


def test_quote_must_come_from_proposed_source_not_an_alternative():
    class Decoder:
        calls = []
        def complete(self, role, system, request, schema):
            from evaluation.review_double import review_checks
            findings = [{"check": "reporting_scope", "evidence_field": "nearby_context", "evidence_quote": "Americas segment", "reason": "Not consolidated"}]
            return schema.model_validate({"verdict": "FAIL", "error_type": "wrong_context", "confidence": 0.9,
                "reason": "Segment scope", "findings": findings, "checks": review_checks(request, findings)})
    with pytest.raises((VerifierContractError, ValidationError)):
        verify(Decoder(), payload())


def test_recovery_must_respect_expansion_flag():
    class Decoder:
        def complete(self, *args):
            return Correction(decision="EXPAND_SEARCH", evidence_id=None, confidence=0.9, reason="More search")
    with pytest.raises(Exception, match="forbidden"):
        correct(Decoder(), {"available_candidates": [], "expansion_allowed": False})


def test_actual_missing_context_can_be_uncertain_without_inventing_requirements():
    class Decoder:
        calls = []
        def complete(self, role, system, request, schema):
            return schema.model_validate({"verdict": "UNCERTAIN", "error_type": "wrong_context", "confidence": 0.5,
                "reason": "No supplied context establishes reporting scope", "findings": [{"check": "reporting_scope", "evidence_field": "nearby_context",
                    "observation": "missing_field", "evidence_quote": "", "reason": "Reporting scope context is absent"}],
                "checks": [{"check": "reporting_scope", "evidence_field": "nearby_context", "observation": "missing_field", "evidence_quote": "", "reason": "Reporting scope context is absent", "status": "UNCERTAIN"}]})
    request = payload()
    request["proposed_evidence"]["nearby_context"] = ""
    assert verify(Decoder(), request).verdict == "UNCERTAIN"
    with pytest.raises((VerifierContractError, ValidationError)):
        verify(Decoder(), payload())


def test_pass_requires_per_check_evidence_not_only_a_reason():
    with pytest.raises(ValidationError):
        Verification(verdict="PASS", error_type="none", confidence=1.0, reason="Everything looks fine")
    class Decoder:
        calls = []
        def complete(self, role, system, request, schema):
            return schema.model_validate({"verdict": "PASS", "error_type": "none", "confidence": 1.0,
                "reason": "Everything looks fine", "checks": []})
    with pytest.raises((VerifierContractError, ValidationError)):
        verify(Decoder(), payload())


def test_scope_pass_requires_an_explicit_consolidated_source_observation():
    class Decoder:
        calls = []
        def complete(self, role, system, request, schema):
            return schema.model_validate({"verdict": "PASS", "error_type": "none", "confidence": 1.0,
                "reason": "Scope is not applicable", "checks": [{"check": "reporting_scope", "status": "PASS",
                    "evidence_field": "nearby_context", "evidence_quote": "In millions", "reason": "No scope issue"}]})
    with pytest.raises((VerifierContractError, ValidationError)):
        verify(Decoder(), payload())


def test_recovery_cannot_expand_for_an_invented_certificate_even_with_budget():
    class Decoder:
        def complete(self, *args):
            return Correction(decision="EXPAND_SEARCH", evidence_id=None, confidence=0.9, reason="Revenue requires a missing accounting identity certificate")
    with pytest.raises(Exception, match="optional Python"):
        correct(Decoder(), {"available_candidates": [], "expansion_allowed": True})


def test_python_aggregates_findings_and_verdict_from_grounded_check_observations():
    result = Verification.model_validate({"verdict": "PASS", "error_type": "none", "confidence": 0.9,
        "reason": "Raw model summary is not authoritative", "findings": [],
        "checks": [{"check": "concept_match", "status": "FAIL", "evidence_field": "label",
                    "evidence_quote": "Total cost of sales", "reason": "Cost of sales is not revenue"}]})
    assert result.verdict == "FAIL"
    assert result.error_type == "wrong_line_item"
    assert len(result.findings) == 1
    assert result.findings[0].evidence_quote == "Total cost of sales"
