"""Source-ID observations for offline doubles; these do not measure model quality."""


def review_checks(payload, findings=None):
    findings = findings or []
    catalogue = payload["evidence_catalogue"]
    records = []
    for check in payload["verification_contract"]["open_checks"]:
        negative = next((f for f in findings if f["check"] == check), None)
        candidates = [item for item in catalogue if check in item["checks"]]
        if negative:
            candidates = [item for item in candidates if negative["evidence_quote"] in item["text"]]
            records.append({"check": check, "status": "FAIL", "reason_code": "contradiction",
                "evidence_ids": [candidates[0]["id"]] if candidates else ["foreign-source"], "reason": negative["reason"]})
        else:
            if check == "reporting_scope":
                supported = [item for item in candidates if item["scope"] == "ESTABLISHED"]
                status = "PASS" if supported else "UNCERTAIN"
                candidates = supported or candidates
            else:
                status = "PASS"
            records.append({"check": check, "status": status,
                "reason_code": "supported" if status == "PASS" else "insufficient_evidence",
                "evidence_ids": [candidates[0]["id"]] if candidates else [], "reason": "Offline source-ID observation"})
    return records


def review_response(payload, answer):
    return {"checks": review_checks(payload, answer.get("findings")),
            "reason": answer.get("reason", "Offline source review"), "confidence": answer.get("confidence", 1.0)}
