"""Unit-aware runtime concept policy and independently checked accounting identities."""
from decimal import Decimal
from typing import TypedDict
from ..config.financial_concepts import CONCEPTS, REVENUE_LABELS
from ..retrieval.lexical_retriever import lexical_signals
from .numeric_parser import normalize
from .validation import eligibility, compatible_inputs, EvidenceError


class RevenuePolicy(TypedDict):
    preferred_evidence_ids: list[str]
    conflicting_periods: list[str]


def revenue_policy(rows, periods, filing_hash) -> RevenuePolicy:
    """Find reported totals without treating a partial total as permission to use sales."""
    known_ids = {r.evidence_id for r in rows}
    totals = []
    for row in rows:
        if normalize(row.label) not in REVENUE_LABELS["reported_total"]:
            continue
        available = [p for p in periods if any(f.period == p for f in row.facts)]
        if available and eligibility(row, "revenue", available, filing_hash, known_ids)["passed"]:
            totals.append(row)
    conflicts = []
    for period in periods:
        reported = {(f.value, f.currency, f.start, f.end)
                    for row in totals for f in row.facts if f.period == period}
        if len(reported) > 1:
            conflicts.append(period)
    return {"preferred_evidence_ids": [r.evidence_id for r in totals], "conflicting_periods": conflicts}


def assess_revenue_basis(row, policy: RevenuePolicy):
    if policy["conflicting_periods"]:
        return {"status": "FAIL", "basis": "unresolved", **policy,
                "reason": "Conflicting reported consolidated revenue totals for " + ", ".join(policy["conflicting_periods"])}
    if policy["preferred_evidence_ids"] and row.evidence_id not in policy["preferred_evidence_ids"]:
        return {"status": "FAIL", "basis": "different_from_reported_total", **policy,
                "reason": "Registered revenue metrics require the separately reported consolidated revenue total; this row cannot replace it"}
    net_sales = normalize(row.label) in REVENUE_LABELS["net_sales"]
    return {"status": "PASS", "basis": "net_sales" if net_sales else "reported_revenue", **policy,
            "reason": ("Net sales is supported as the revenue line; no separate reported consolidated revenue total was found for the requested periods"
                       if net_sales else "Uses the reported revenue basis")}


def assess_concept(row, component, periods, filing_hash, known_ids, *, revenue_basis_policy=None):
    mechanical = eligibility(row, component, periods, filing_hash, known_ids)
    if not mechanical["passed"]:
        failed = ", ".join(k for k, v in mechanical["checks"].items() if not v)
        return {"status": "FAIL", "reason": "Source/unit/period constraints failed: " + failed}
    basis = assess_revenue_basis(row, revenue_basis_policy) if component == "revenue" and revenue_basis_policy is not None else None
    details = {"revenue_basis": basis} if basis is not None else {}
    if basis is not None and basis["status"] != "PASS":
        return {"status": "FAIL", "reason": basis["reason"], **details}
    _, exact, xbrl = lexical_signals(row, component)
    expected = CONCEPTS[component][2]
    reported = {f.concept.split(":")[-1] for f in row.facts if f.period in periods and f.concept}
    if reported and not reported.issubset(set(expected)):
        return {"status": "UNCERTAIN", "reason": "Reported taxonomy concepts do not uniformly match the required concept", **details}
    if exact or xbrl:
        return {"status": "PASS", "reason": "Registered accounting concept matches the statement and monetary dimension; label equivalence is unit-aware", **details}
    return {"status": "UNCERTAIN", "reason": "No unambiguous registered label or taxonomy concept supports this row", **details}


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
