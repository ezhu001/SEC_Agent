"""Observable step summaries; no model private reasoning or UI dependencies."""
LABELS = {
    "validate_request": "Validate question and source",
    "load_filing": "Load filing and identify source",
    "plan_task": "Resolve registered formula, components and fiscal periods",
    "build_evidence": "Parse statements and construct evidence",
    "check_inputs": "Check all required components and years",
    "retrieve_component": "FinBERT and hybrid evidence retrieval",
    "assess_sufficiency": "Assess evidence sufficiency",
    "expand_search": "Expand evidence search",
    "verify": "Verify evidence: source rules / optional Qwen",
    "guard": "Check source, periods, units and values",
    "correct": "Recover evidence within configured mode",
    "next_component": "Advance accepted evidence",
    "calculate": "Calculate with validated evidence",
    "finish": "Build result and save audit",
}


def summary(node, state):
    c = state.get("active_component", "")
    if node == "load_filing":
        return state.get("filing_metadata", {}).get("entity", "Filing loaded")
    if node == "plan_task":
        return f"{state.get('formula_id', state.get('final_status', ''))}; {', '.join(state.get('required_periods', []))}"
    if node == "build_evidence":
        return f"{len(state.get('parsed_statements', []))} statement tables parsed"
    if node == "check_inputs":
        cells = state.get("input_inventory", [])
        return "; ".join(f"{c['component']} {c['period']}: {c['status']}" for c in cells)
    if node in {"retrieve_component", "expand_search"}:
        candidates = state.get("retrieval_results", {}).get(c, [])
        return f"{c}: {len(candidates)} candidates" + (f"; proposed: {candidates[0]['label']}" if candidates else "")
    if node == "assess_sufficiency":
        records = state.get("evidence_sufficiency", {}).get(c, [])
        return records[-1]["status"] + ": " + records[-1]["reason"] if records else ""
    if node == "verify":
        records = state.get("verification_results", {}).get(c, [])
        return records[-1]["verdict"] + " [" + records[-1].get("method", "qwen") + "]: " + records[-1]["reason"] if records else ""
    if node == "guard":
        records = state.get("guard_results", {}).get(c, [])
        if records:
            return "PASS" if records[-1]["passed"] else "Failed: " + ", ".join(k for k, v in records[-1]["checks"].items() if not v)
    if node == "correct":
        records = state.get("correction_results", {}).get(c, [])
        return records[-1]["decision"] + ": " + records[-1]["reason"] if records else "No replacement established"
    if node == "calculate" and state.get("calculation_result"):
        calc = state["calculation_result"]
        return f"{calc['value']:.6g} {calc['unit']}"
    return state.get("final_status", "")
