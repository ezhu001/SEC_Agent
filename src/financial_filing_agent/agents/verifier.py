from ..config.prompts import VERIFIER
from ..schemas.results import Verification
from .verification_contract import build_contract, validate_review, VerifierContractError, review_schema, evidence_catalogue
import json


def verify(decoder, payload):
    request = dict(payload)
    request["verification_contract"] = build_contract(request)
    # Do not send an UNAVAILABLE sentinel for an inapplicable certificate.
    request.pop("accounting_identity", None)
    request.pop("alternatives", None)  # Alternative selection belongs only to recovery.
    if not request["verification_contract"]["open_checks"]:
        return Verification(verdict="PASS", error_type="none", confidence=1.0,
                            reason="All required checks established by Python source evidence", checks=[])
    request["evidence_catalogue"] = evidence_catalogue(request)
    schema = review_schema(tuple(request["verification_contract"]["open_checks"]), json.dumps(request["evidence_catalogue"], ensure_ascii=False, sort_keys=True))
    for attempt in range(2):
        result = decoder.complete("verifier", VERIFIER, request, schema)
        try:
            resolved = validate_review(result, request)
        except VerifierContractError as exc:
            if getattr(decoder, "calls", None):
                decoder.calls[-1]["contract_validation"] = {"passed": False, "error": str(exc)}
            if attempt == 1:
                raise
            request["contract_feedback"] = str(exc) + ". Review the original row only. Do not change the required checks. Return a corrected structured review."
            continue
        if getattr(decoder, "calls", None):
            decoder.calls[-1]["contract_validation"] = {"passed": True}
        return resolved
