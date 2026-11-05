"""Unit-aware runtime concept policy and independently checked accounting identities."""
from decimal import Decimal
from ..config.financial_concepts import CONCEPTS
from ..retrieval.lexical_retriever import lexical_signals
from .validation import guard, compatible_inputs, EvidenceError


def assess_concept(row, component, periods, filing_hash, known_ids):
    mechanical = guard(row, component, periods, filing_hash, row.evidence_id, known_ids)
    if not mechanical["passed"]:
        failed = ", ".join(k for k, v in mechanical["checks"].items() if not v)
        return {"status": "FAIL", "reason": "Source/unit/period constraints failed: " + failed}
    _, exact, xbrl = lexical_signals(row, component)
    expected = CONCEPTS[component][2]
    reported = {f.concept.split(":")[-1] for f in row.facts if f.period in periods and f.concept}
    if reported and not reported.issubset(set(expected)):
        return {"status": "UNCERTAIN", "reason": "Reported taxonomy concepts do not uniformly match the required concept"}
    if exact or xbrl:
        return {"status": "PASS", "reason": "Registered accounting concept matches the statement and monetary dimension; label equivalence is unit-aware"}
    return {"status": "UNCERTAIN", "reason": "No unambiguous registered label or taxonomy concept supports this row"}


def gross_profit_identity(row, rows, periods):
    """Certify a reported monetary subtotal; never generate replacement facts."""
    if row.statement != "operations":
        return {"status": "UNAVAILABLE", "reason": "Not an operations statement"}
    selected = {"gross_profit": row}
    for component in ("revenue", "cost_of_sales"):
        candidates = [r for r in rows if r.table == row.table and r.filing_hash == row.filing_hash
            and assess_concept(r, component, periods, row.filing_hash, {x.evidence_id for x in rows})["status"] == "PASS"]
        if len(candidates) != 1:
            return {"status": "UNAVAILABLE", "reason": f"No unique same-table {component} evidence"}
        selected[component] = candidates[0]
    try:
        compatible_inputs(selected, periods, allow_currency_cancellation=True)
    except EvidenceError as exc:
        return {"status": "UNAVAILABLE", "reason": str(exc)}
    checks = []
    for period in periods:
        values = {c: Decimal(str(next(f.value for f in r.facts if f.period == period))) for c, r in selected.items()}
        computed = values["revenue"] - values["cost_of_sales"]
        checks.append({"period": period, "reported_gross_profit": float(values["gross_profit"]),
                       "revenue_minus_cost_of_sales": float(computed), "passed": computed == values["gross_profit"]})
    return {"status": "PASS" if all(c["passed"] for c in checks) else "MISMATCH",
            "rule": "reported monetary gross profit = revenue - cost of sales",
            "checks": checks, "source_evidence_ids": {c: r.evidence_id for c, r in selected.items()}}
