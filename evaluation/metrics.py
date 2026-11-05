def evaluate(result, expected_value=None, tolerance=None, expected_ids=None):
    """Gold joins only after execution. Abstention is not automatically correct."""
    calc = result.get("calculation_result")
    answered = result["final_status"] == "SUCCESS" and calc is not None
    correct = answered and expected_value is not None and abs(calc["value"] - expected_value) <= tolerance
    return {"status": result["final_status"], "answered": answered, "derived_claim_correct": bool(correct),
            "component_matches": {c: ident == expected_ids.get(c) for c, ident in result["accepted_evidence"].items()} if expected_ids else {},
            "direction_correct": bool(answered and expected_value is not None and calc["direction"] == (1 if expected_value > 0 else -1 if expected_value < 0 else 0)),
            "useful_completion": bool(answered), "operational_failure": result["final_status"] == "ERROR"}
