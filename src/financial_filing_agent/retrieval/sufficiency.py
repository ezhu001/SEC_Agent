def assess(ranked):
    if not ranked:
        return {"status": "INSUFFICIENT", "reason": "No candidate evidence in searched scope"}
    supported = [r for r in ranked if r["signals"]["statement"] and r["signals"]["periods"] and r["signals"]["numeric"]]
    if not supported:
        return {"status": "INSUFFICIENT", "reason": "No row supplies required statement, periods and values"}
    top = ranked[0]["signals"]
    if top["statement"] and top["periods"] and (top["exact_label"] or top["xbrl"]):
        return {"status": "SUFFICIENT", "reason": "Structural and concept support present; semantic verification still required"}
    if not (top["statement"] and top["periods"] and top["numeric"]):
        return {"status": "INSUFFICIENT", "reason": "Proposed row lacks the required statement, periods or values; other candidates cannot supply its missing facts"}
    return {"status": "UNCERTAIN", "reason": "Ranking alone does not establish exact concept; broaden search or audit with decoder"}
