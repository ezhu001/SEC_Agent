"""Executable review boundaries independent of the model's prose reasoning."""
import json
import re
from functools import lru_cache
from typing import Literal, Union
from pydantic import create_model, Field
from ..models.local_decoder import DecoderError
from ..config.formulas import FORMULAS
from ..schemas.results import Verification, VerificationFinding, VerificationCheck


class VerifierContractError(DecoderError):
    pass


CHECK_FIELDS = {
    "concept_match": {"label", "facts", "nearby_context"},
    "statement_match": {"statement", "nearby_context"},
    "required_periods": {"facts", "nearby_context"},
    "monetary_unit": {"facts", "nearby_context"},
    "reporting_scope": {"facts", "nearby_context"},
    "formula_role": {"label", "facts", "nearby_context"},
}
CHECK_DEFINITIONS = {
    "concept_match": "Does this reported financial line item mean the required accounting concept? Sales and cost of sales differ.",
    "statement_match": "Operations statement versus balance sheet; not revenue section versus expense section.",
    "required_periods": "Requested fiscal periods and annual/instant context; do not add extra years or certificates.",
    "monetary_unit": "Monetary amount versus percent/ratio and source unit compatibility under Python policy.",
    "reporting_scope": "Consolidated company versus segment/product/geographical/parent-only scope. Revenue and cost sections within the same consolidated statement have the same reporting scope.",
    "formula_role": "This one component's registered numerator/denominator/input role; other components are reviewed separately.",
}
ERROR_CHECKS = {
    "wrong_line_item": {"concept_match"}, "wrong_statement": {"statement_match"},
    "wrong_period": {"required_periods"}, "unit_or_value_problem": {"monetary_unit", "required_periods"},
    "wrong_formula_role": {"formula_role"}, "wrong_context": {"reporting_scope"},
    "insufficient_evidence": set(CHECK_FIELDS),
}


def build_contract(payload):
    row = payload["proposed_evidence"]
    facts = [f for f in row.get("facts", []) if f["period"] in payload["required_periods"]]
    frozen = {}
    if payload.get("deterministic_concept_assessment", {}).get("status") == "PASS":
        frozen["concept_match"] = "Registered concept/alias and monetary dimension already confirmed by Python"
        formula = FORMULAS.get(payload.get("formula_id"))
        if formula and payload["required_component"] in formula.components:
            frozen["formula_role"] = "This component's role is fixed by the registered formula; other formula components are reviewed separately"
    if row["statement"] == payload["expected_statement"]:
        frozen["statement_match"] = "Source statement matches the required statement"
    if all(sum(f["period"] == p for f in facts) == 1 for p in payload["required_periods"]):
        frozen["required_periods"] = "Each requested period has exactly one source fact"
    if facts and all(f.get("unit") == "currency" and (f.get("currency") or f.get("unit_basis")) for f in facts):
        frozen["monetary_unit"] = "Explicit compatible monetary dimension; unspecified currency may cancel under Python's policy"
    return {"version": "1", "task": "audit this one supplied row for this one component",
            "allowed_checks": [c for c in CHECK_FIELDS if c not in frozen], "resolved_by_python": frozen,
            "open_checks": [c for c in CHECK_FIELDS if c not in frozen],
            "check_definitions": {c: CHECK_DEFINITIONS[c] for c in CHECK_FIELDS if c not in frozen},
            "required_check_results": len(CHECK_FIELDS) - len(frozen),
            "certificate_requirement": "NONE: accounting identities are optional Python-only checks, not prerequisites",
            "error_type_checks": {name: sorted(checks & (set(CHECK_FIELDS) - set(frozen))) for name, checks in ERROR_CHECKS.items() if checks - set(frozen)},
            "permitted_outcomes": "PASS, or FAIL/UNCERTAIN with a verbatim source quote for an open allowed check",
            "forbidden_actions": ["calculate", "demand an accounting identity", "invent required evidence", "select a replacement", "expand search"]}


@lru_cache(maxsize=64)
def review_schema(open_checks, source_json="{}"):
    """Bind JSON grammar to this request, including nonempty exact check count."""
    source = json.loads(source_json)
    finding_types, check_types = [], []
    for name in open_checks:
        fields = ("nearby_context",) if name == "reporting_scope" else tuple(sorted(CHECK_FIELDS[name]))
        overrides = {"check": (Literal.__getitem__((name,)), ...),
                     "evidence_field": (Literal.__getitem__(fields), ...)}
        if name == "reporting_scope":
            context = source.get("nearby_context", "")
            quotes = [context[:300], context[-300:]]
            for match in re.finditer(r"consolidated", context, re.I):
                quotes.append(context[match.start():match.start() + 80])
                heading = re.match(r"consolidated\s+(?:statements?\s+of\s+[A-Za-z '’]+|balance\s+sheets?)", context[match.start():], re.I)
                if heading:
                    quotes.append(heading.group().rstrip())
            overrides["evidence_quote"] = (Literal.__getitem__(tuple(dict.fromkeys(quotes))), ...)
            observation = "quote" if context else "missing_field"
            overrides["observation"] = (Literal.__getitem__((observation,)), Field(default=observation))
        finding_types.append(create_model(name + "Finding", __base__=VerificationFinding, **overrides))
        check_types.append(create_model(name + "Check", __base__=VerificationCheck, **overrides))
    finding = finding_types[0] if len(finding_types) == 1 else Union.__getitem__(tuple(finding_types))
    check = check_types[0] if len(check_types) == 1 else Union.__getitem__(tuple(check_types))
    return create_model("BoundedVerification", __base__=Verification,
        error_type=(Literal.__getitem__(tuple(["none"] + [name for name, checks in ERROR_CHECKS.items() if checks & set(open_checks)])), ...),
        findings=(list[finding], Field(default_factory=list, max_length=len(open_checks))),
        checks=(list[check], Field(min_length=len(open_checks), max_length=len(open_checks))))


def validate_review(result, payload):
    contract = payload["verification_contract"]
    if result.verdict != "PASS" and re.search(r"accounting[ _-]*identity|certificate|reconcil", result.reason + " " + " ".join(f.reason for f in result.findings), re.I):
        raise VerifierContractError("Optional Python accounting certificates cannot become required decoder evidence")
    if result.findings and not any(f.check in ERROR_CHECKS.get(result.error_type, set()) for f in result.findings):
        raise VerifierContractError("error_type does not match any cited blocking check")
    for finding in result.findings:
        if finding.check in contract["resolved_by_python"]:
            raise VerifierContractError(f"Cannot reopen Python-resolved {finding.check}; quote an actual open source-context contradiction instead")
    reviewed = [c.check for c in result.checks]
    if len(reviewed) != len(set(reviewed)) or set(reviewed) != set(contract["open_checks"]):
        raise VerifierContractError("Return exactly one structured check result with source evidence for every open check, and none for resolved checks")
    negative = {c.check for c in result.checks if c.status != "PASS"}
    expected_verdict = "FAIL" if any(c.status == "FAIL" for c in result.checks) else "UNCERTAIN" if negative else "PASS"
    if result.verdict != expected_verdict or negative != {f.check for f in result.findings}:
        raise VerifierContractError("Overall verdict, per-check statuses and blocking findings disagree")
    for finding in list(result.findings) + list(result.checks):
        if finding.evidence_field not in CHECK_FIELDS[finding.check]:
            raise VerifierContractError("Evidence field does not support the claimed check")
        value = payload["proposed_evidence"].get(finding.evidence_field, "")
        if finding.observation == "missing_field":
            if value:
                raise VerifierContractError("Claimed missing field is actually present in the proposed source row")
            if getattr(finding, "status", None) == "PASS":
                raise VerifierContractError("A missing source field cannot certify a PASS")
            continue
        source = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        if finding.evidence_quote not in source:
            raise VerifierContractError("Finding quote is absent from the cited field of the proposed source row")
        if finding.check == "reporting_scope" and getattr(finding, "status", None) == "PASS":
            if finding.evidence_field != "nearby_context" or not re.search(r"\bconsolidated\b", finding.evidence_quote, re.I):
                raise VerifierContractError("A consolidated-scope PASS must cite the actual consolidated statement heading/context")
