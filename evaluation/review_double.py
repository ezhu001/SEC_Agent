"""Structured source observations for offline workflow doubles, not model results."""
import json


def review_checks(payload, findings=None):
    findings = findings or []
    row = payload["proposed_evidence"]
    records = []
    for check in payload["verification_contract"]["open_checks"]:
        negative = next((f for f in findings if f["check"] == check), None)
        if negative:
            records.append({**negative, "status": "FAIL"})
        else:
            field = {"reporting_scope": "nearby_context", "required_periods": "facts",
                     "monetary_unit": "facts", "statement_match": "statement"}.get(check, "label")
            value = row.get(field, "")
            if check == "reporting_scope" and isinstance(value, str) and "consolidated" in value.lower():
                value = value[value.lower().index("consolidated"):]
            records.append({"check": check, "status": "PASS", "evidence_field": field,
                            "evidence_quote": (value if isinstance(value, str) else json.dumps(value))[:80], "reason": "Offline test observation"})
    return records
