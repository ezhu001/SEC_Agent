import pytest
from pydantic import ValidationError

from evaluation.doubles import DemoRetriever
from evaluation.review_double import review_response
from financial_filing_agent.agents.corrector import correct
from financial_filing_agent.agents.verification_contract import VerifierContractError, build_contract
from financial_filing_agent.agents.verifier import verify
from financial_filing_agent.config.financial_concepts import definition
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.schemas.results import Correction, Verification
from financial_filing_agent.services.pipeline import Pipeline


def payload(context="CONSOLIDATED STATEMENTS OF OPERATIONS (In millions)"):
    return {"required_component": "revenue", "formula_id": "revenue_growth", "required_periods": ["FY2025"],
        "filing_hash": "filing", "expected_statement": "operations", "concept_definition": definition("revenue"),
        "deterministic_concept_assessment": {"status": "PASS"},
        "proposed_evidence": {"evidence_id": "row", "label": "Total net sales", "statement": "operations",
            "nearby_context": context, "facts": [{"period": "FY2025", "value": 110, "unit": "currency", "currency": "USD"}]},
        "accounting_identity": {"status": "UNAVAILABLE"}}


def good(request):
    return review_response(request, {"reason": "Source-backed observation"})


class Decoder:
    def __init__(self, response=good):
        self.calls, self.response = [], response

    def complete(self, role, system, request, schema):
        self.calls.append({"role": role, "request": request.copy()})
        return schema.model_validate(self.response(request))


def observation(request, status, reason="Source review", item=None):
    candidates = request["evidence_catalogue"]
    ident = item or next(c["id"] for c in candidates if "reporting_scope" in c["checks"])
    return {"checks": [{"check": "reporting_scope", "status": status, "evidence_ids": [ident],
        "reason_code": {"PASS": "supported", "FAIL": "contradiction", "UNCERTAIN": "insufficient_evidence"}[status],
        "reason": reason}]}


def test_contract_lists_open_checks_and_has_a_new_version():
    contract = build_contract(payload())
    assert contract["version"] == "2"
    assert contract["open_checks"] == ["reporting_scope"]
    assert set(contract["resolved_by_python"]) == {"concept_match", "statement_match", "required_periods", "monetary_unit", "formula_role"}


def test_source_ids_are_resolved_to_original_quotes_and_optional_fields_are_omitted():
    decoder = Decoder()
    request = payload()
    request["alternatives"] = [{"label": "Distracting row"}]
    result = verify(decoder, request)
    assert result.verdict == "PASS"
    assert result.checks[0].evidence_ids == ["row:context"]
    assert result.checks[0].evidence_quote == request["proposed_evidence"]["nearby_context"]
    assert "accounting_identity" not in decoder.calls[0]["request"]
    assert "alternatives" not in decoder.calls[0]["request"]


def test_all_resolved_checks_skip_the_decoder():
    request = payload()
    request["scope_assessment"] = {"status": "ESTABLISHED", "reason": "Established issuer source"}
    decoder = Decoder()
    result = verify(decoder, request)
    assert result.verdict == "PASS" and not result.checks
    assert not decoder.calls


def test_one_contract_repair_is_bounded_and_can_succeed():
    def response(request):
        return good(request) if "contract_feedback" in request else observation(request, "UNCERTAIN", "Missing accounting identity certificate")
    decoder = Decoder(response)
    assert verify(decoder, payload()).verdict == "PASS"
    assert len(decoder.calls) == 2
    assert decoder.calls[0]["contract_validation"]["passed"] is False
    assert decoder.calls[1]["contract_validation"]["passed"] is True


def test_persistent_invented_requirement_is_an_error_not_evidence_for_recovery():
    decoder = Decoder(lambda request: observation(request, "UNCERTAIN", "Missing required accounting identity certificate"))
    with pytest.raises(VerifierContractError, match="Optional Python"):
        verify(decoder, payload())
    assert len(decoder.calls) == 2


def test_invalid_review_cannot_trigger_corrector_or_expansion(tmp_path):
    decoder = Decoder(lambda request: observation(request, "UNCERTAIN", "Missing required accounting identity certificate"))
    result = Pipeline(Settings(artifact_dir=tmp_path), decoder, DemoRetriever()).run(
        "", "evaluation/fixtures/demo.html", ["FY2025", "FY2024"], formula_id="revenue_growth")
    assert result["final_status"] == "ERROR"
    assert result["errors"][0]["type"] == "VerifierContractError"
    assert result["correction_count"] == result["expanded_search_count"] == 0
    assert not result["calculation_result"]


@pytest.mark.parametrize("ident", ["foreign:context", "row:label"])
def test_unknown_ids_and_wrong_evidence_types_are_rejected(ident):
    decoder = Decoder(lambda request: observation(request, "PASS", item=ident))
    with pytest.raises((VerifierContractError, ValidationError)):
        verify(decoder, payload())


@pytest.mark.parametrize("context", ["In millions", "BALANCE SHEETS", "Discussion of consolidated annual performance"])
def test_a_scope_pass_requires_actual_scope_support_not_a_keyword_or_statement_type(context):
    decoder = Decoder(lambda request: observation(request, "PASS"))
    with pytest.raises(VerifierContractError, match="does not establish"):
        verify(decoder, payload(context))
    assert len(decoder.calls) == 2


def test_unresolved_scope_is_a_valid_uncertain_review():
    result = verify(Decoder(lambda request: observation(request, "UNCERTAIN")), payload("BALANCE SHEETS"))
    assert result.verdict == "UNCERTAIN"
    assert result.findings[0].evidence_ids == ["row:context"]


def test_absent_scope_evidence_allows_uncertain_but_not_pass():
    def response(request):
        return {"checks": [{"check": "reporting_scope", "status": "UNCERTAIN", "evidence_ids": [],
                "reason_code": "insufficient_evidence", "reason": "No scope evidence supplied"}]}
    result = verify(Decoder(response), payload(""))
    assert result.verdict == "UNCERTAIN"
    assert result.checks[0].observation == "missing_field"
    assert result.checks[0].evidence_quote == ""
    bad = Decoder(lambda request: {"checks": [{**response(request)["checks"][0], "status": "PASS", "reason_code": "supported"}]})
    with pytest.raises(VerifierContractError):
        verify(bad, payload(""))


def test_positive_scope_evidence_cannot_be_used_as_a_scope_contradiction():
    with pytest.raises(VerifierContractError, match="does not establish"):
        verify(Decoder(lambda request: observation(request, "FAIL")), payload())


def test_resolved_checks_cannot_be_reopened():
    decoder = Decoder(lambda request: {"checks": [{"check": "concept_match", "status": "FAIL", "evidence_ids": ["row:label"],
        "reason_code": "contradiction", "reason": "Display name differs"}]})
    with pytest.raises((ValidationError, VerifierContractError)):
        verify(decoder, payload())


def test_status_and_reason_code_must_agree():
    def response(request):
        result = observation(request, "UNCERTAIN")
        result["checks"][0]["reason_code"] = "supported"
        return result
    with pytest.raises(VerifierContractError, match="reason_code"):
        verify(Decoder(response), payload())


def test_json_schema_binds_evidence_ids_to_each_check_not_the_whole_catalogue():
    request = payload()
    request["scope_assessment"] = {"status": "ESTABLISHED", "reason": "Issuer statement verified"}
    request["deterministic_concept_assessment"] = {"status": "UNCERTAIN"}
    request["proposed_evidence"]["facts"][0]["unit"] = None
    def response(sent):
        checks = good(sent)["checks"]
        for check in checks:
            if check["check"] == "monetary_unit":
                check["evidence_ids"] = ["row:label"]
        return {"checks": checks}
    # A label ID exists in this catalogue, but the monetary-unit grammar must exclude it.
    with pytest.raises(ValidationError):
        verify(Decoder(response), request)


def test_raw_quotes_are_not_an_agent_response_field():
    def response(request):
        result = good(request)
        result["checks"][0]["evidence_quote"] = "Invented heading"
        return result
    with pytest.raises(ValidationError):
        verify(Decoder(response), payload())


def test_a_heading_from_a_foreign_filing_cannot_enter_the_catalogue():
    request = payload()
    request["proposed_evidence"]["statement_heading"] = {"text": "CONSOLIDATED STATEMENTS OF OPERATIONS",
        "filing_hash": "foreign", "locator": "element:1"}
    decoder = Decoder()
    with pytest.raises(VerifierContractError, match="different filing"):
        verify(decoder, request)
    assert not decoder.calls


def test_pass_requires_all_open_observations():
    with pytest.raises(ValidationError):
        verify(Decoder(lambda request: {"checks": []}), payload())


def test_python_aggregates_verdict_from_checks():
    result = Verification.model_validate({"verdict": "PASS", "error_type": "none", "confidence": 0.9,
        "reason": "Model summary is not authoritative", "checks": [{"check": "concept_match", "status": "FAIL",
            "evidence_field": "label", "evidence_quote": "Cost of sales", "reason": "Different concept"}]})
    assert result.verdict == "FAIL" and result.error_type == "wrong_line_item"


def test_recovery_respects_expansion_budget_and_optional_checks():
    class Expand:
        def complete(self, *args):
            return Correction(decision="EXPAND_SEARCH", evidence_id=None, confidence=1.0, reason="More source evidence")
    with pytest.raises(Exception, match="forbidden"):
        correct(Expand(), {"available_candidates": [], "expansion_allowed": False})
    class Invented:
        def complete(self, *args):
            return Correction(decision="EXPAND_SEARCH", evidence_id=None, confidence=1.0, reason="Missing accounting identity certificate")
    with pytest.raises(Exception, match="optional Python"):
        correct(Invented(), {"available_candidates": [], "expansion_allowed": True})
