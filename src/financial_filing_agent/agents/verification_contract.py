"""Executable review boundaries independent of the model's prose reasoning."""
import json
import re
from functools import lru_cache
from typing import Literal, Union
from pydantic import create_model, Field
from ..models.local_decoder import DecoderError
from ..config.formulas import FORMULAS
from ..schemas.results import Verification, AgentReview, AgentCheck


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
    if payload.get("scope_assessment", {}).get("status") == "ESTABLISHED":
        frozen["reporting_scope"] = payload["scope_assessment"]["reason"]
    return {"version": "2", "task": "audit this one supplied row for this one component",
            "allowed_checks": [c for c in CHECK_FIELDS if c not in frozen], "resolved_by_python": frozen,
            "open_checks": [c for c in CHECK_FIELDS if c not in frozen],
            "check_definitions": {c: CHECK_DEFINITIONS[c] for c in CHECK_FIELDS if c not in frozen},
            "required_check_results": len(CHECK_FIELDS) - len(frozen),
            "certificate_requirement": "NONE: accounting identities are optional Python-only checks, not prerequisites",
            "error_type_checks": {name: sorted(checks & (set(CHECK_FIELDS) - set(frozen))) for name, checks in ERROR_CHECKS.items() if checks - set(frozen)},
            "permitted_outcomes": "PASS, FAIL or UNCERTAIN with source evidence IDs for each open check",
            "forbidden_actions": ["calculate", "demand an accounting identity", "invent required evidence", "select a replacement", "expand search"]}


def evidence_catalogue(payload):
    row = payload["proposed_evidence"]
    if row.get("filing_hash", payload.get("filing_hash")) != payload.get("filing_hash"):
        raise VerifierContractError("Proposed source belongs to a different filing")
    ident = row["evidence_id"]
    catalogue = []
    def add(suffix, field, text, checks, scope="UNRESOLVED", locator=None):
        if text:
            catalogue.append({"id": ident + ":" + suffix, "row_id": ident,
                "filing_hash": payload.get("filing_hash"), "field": field, "text": text,
                "locator": locator or f"table:{row.get('table')}:row:{row.get('row')}:{suffix}",
                "checks": checks, "scope": scope})
    add("label", "label", row["label"], ["concept_match", "formula_role"])
    add("statement", "statement", row["statement"], ["statement_match"])
    for i, fact in enumerate(row.get("facts", [])):
        add(f"fact:{i}", "facts", json.dumps(fact, ensure_ascii=False, sort_keys=True),
            ["concept_match", "required_periods", "monetary_unit", "formula_role"])
    context = row.get("nearby_context", "")
    heading = row.get("statement_heading")
    heading_text = heading.get("text", "") if heading else ""
    # A literal statement heading can support the agent's scope interpretation.
    # Bare 'consolidated' elsewhere in prose cannot do so.
    explicit = re.search(r"consolidated\s+(balance\s+sheets?|statements?\s+of\s+(?:operations|income|earnings))", heading_text if "statement_heading" in row else context, re.I)
    matches_statement = explicit and (("balance" in explicit.group().lower()) == (row["statement"] == "balance"))
    support = "ESTABLISHED" if matches_statement else "UNRESOLVED"
    quoted_heading = explicit and explicit.group() in context
    add("context", "nearby_context", context, ["reporting_scope"], support if quoted_heading else "UNRESOLVED")
    if heading:
        if heading["filing_hash"] != payload.get("filing_hash"):
            raise VerifierContractError("Statement heading belongs to a different filing")
        add("heading", "scope_evidence", heading_text, ["reporting_scope"], support, heading["locator"])
    for i, source in enumerate(payload.get("scope_assessment", {}).get("sources", [])):
        if source["filing_hash"] != payload.get("filing_hash"):
            raise VerifierContractError("Scope source belongs to a different filing")
        add(f"scope:{i}", "scope_evidence", source["text"], ["reporting_scope"],
            payload["scope_assessment"]["status"], source["locator"])
    open_checks = set(payload["verification_contract"]["open_checks"])
    return [{**item, "checks": [c for c in item["checks"] if c in open_checks]}
            for item in catalogue if open_checks.intersection(item["checks"])]


@lru_cache(maxsize=64)
def review_schema(open_checks, catalogue_json="[]"):
    catalogue = json.loads(catalogue_json)
    types = []
    for name in open_checks:
        ids = tuple(item["id"] for item in catalogue if name in item["checks"])
        fields = {"check": (Literal.__getitem__((name,)), ...)}
        fields["evidence_ids"] = ((list[Literal.__getitem__(ids)] if ids else list[str]), Field(max_length=min(6, len(ids))))
        types.append(create_model(name + "AgentCheck", __base__=AgentCheck, **fields))
    check = types[0] if len(types) == 1 else Union.__getitem__(tuple(types))
    return create_model("BoundedAgentReview", __base__=AgentReview,
        checks=(list[check], Field(min_length=len(open_checks), max_length=len(open_checks))))


def resolve_review(result, payload):
    contract = payload["verification_contract"]
    catalogue = {item["id"]: item for item in payload["evidence_catalogue"]}
    reviewed = [c.check for c in result.checks]
    if len(reviewed) != len(set(reviewed)) or set(reviewed) != set(contract["open_checks"]):
        raise VerifierContractError("Return one observation for each open check and none for Python-resolved checks")
    resolved = []
    for check in result.checks:
        if check.status != "PASS" and re.search(r"accounting[ _-]*identity|certificate|reconcil", check.reason, re.I):
            raise VerifierContractError("Optional Python accounting certificates cannot become required decoder evidence")
        code = {"PASS": "supported", "FAIL": "contradiction", "UNCERTAIN": "insufficient_evidence"}[check.status]
        if check.reason_code != code:
            raise VerifierContractError("Status and reason_code disagree")
        if len(check.evidence_ids) != len(set(check.evidence_ids)):
            raise VerifierContractError("Duplicate evidence reference")
        items = []
        for ident in check.evidence_ids:
            item = catalogue.get(ident)
            if not item or item["row_id"] != payload["proposed_evidence"]["evidence_id"] or item["filing_hash"] != payload.get("filing_hash"):
                raise VerifierContractError("Unknown or foreign evidence reference")
            if check.check not in item["checks"]:
                raise VerifierContractError("Evidence type does not support the claimed check")
            items.append(item)
        if not items and check.status != "UNCERTAIN":
            raise VerifierContractError("PASS and FAIL require actual source evidence")
        if check.check == "reporting_scope" and check.status != "UNCERTAIN":
            required = "ESTABLISHED" if check.status == "PASS" else "RESTRICTED"
            if not any(item["scope"] == required for item in items):
                raise VerifierContractError("Source evidence does not establish the claimed scope; use UNCERTAIN")
        resolved.append({"check": check.check, "status": check.status, "evidence_ids": check.evidence_ids,
            "evidence_field": items[0]["field"] if items else "scope_evidence",
            "observation": "quote" if items else "missing_field",
            "evidence_quote": " | ".join(item["text"] for item in items)[:300], "reason": check.reason})
    return Verification.model_validate({"verdict": "PASS", "error_type": "none", "confidence": result.confidence,
        "reason": result.reason, "checks": resolved})


def validate_review(result, payload):
    # Kept as the public validation entry point; the returned audit has resolved source excerpts.
    return resolve_review(result, payload)
