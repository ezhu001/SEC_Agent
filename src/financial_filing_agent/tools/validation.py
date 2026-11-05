import math
from datetime import date
from ..config.financial_concepts import CONCEPTS


class EvidenceError(ValueError):
    pass


def guard(row, component, periods, filing_hash, verified_id, known_ids):
    facts = [f for f in row.facts if f.period in periods]
    checks = {
        "source_membership": row.evidence_id in known_ids and row.filing_hash == filing_hash,
        "label_present": bool(row.label.strip()),
        "statement": row.statement == CONCEPTS[component][0],
        "reverified_selection": verified_id == row.evidence_id,
        "unique_requested_periods": all(sum(f.period == p for f in facts) == 1 for p in periods),
        "finite_values": bool(facts) and all(math.isfinite(f.value) for f in facts),
        "known_units": bool(facts) and all(f.unit == "currency" and (f.currency is not None or f.unit_basis is not None) for f in facts),
        "compatible_currency": len({f.currency for f in facts}) == 1,
        "consolidated": all(not f.dimensions for f in facts),
        "period_kind": all(f.instant == (row.statement == "balance") for f in facts),
        "annual_duration": all(f.instant or not f.start or (f.end and 330 <= (date.fromisoformat(f.end) - date.fromisoformat(f.start)).days <= 380) for f in facts),
    }
    return {"passed": all(checks.values()), "checks": checks, "evidence_id": row.evidence_id}


def compatible_inputs(accepted, periods, *, allow_currency_cancellation=False):
    if not accepted:
        raise EvidenceError("No accepted evidence")
    currency = set()
    for row in accepted.values():
        for period in periods:
            facts = [f for f in row.facts if f.period == period]
            if len(facts) != 1:
                raise EvidenceError("Missing or ambiguous period")
            fact = facts[0]
            if fact.unit != "currency" or not (fact.currency or fact.unit_basis) or not math.isfinite(fact.value) or fact.dimensions:
                raise EvidenceError("Unknown or incompatible unit/currency/context")
            currency.add(fact.currency)
    if len(currency) != 1:
        raise EvidenceError("Mixed currencies")
    if currency == {None}:
        # All registered formulas are dimensionless. An unidentified currency
        # cancels only on one explicitly monetary table basis, never across
        # unrelated tables or a mixture of identified/unidentified currencies.
        bases = {f.unit_basis for row in accepted.values() for f in row.facts if f.period in periods}
        if len(bases) != 1 or None in bases:
            raise EvidenceError("Unknown currencies lack a common monetary source basis")
        if not allow_currency_cancellation:
            raise EvidenceError("An identified currency is required for a dimensional monetary result")
    # Ratio components for each year must describe the same reporting period.
    for p in periods:
        selected = [next(f for f in row.facts if f.period == p) for row in accepted.values()]
        ends = {f.end for f in selected}
        starts = {f.start for f in selected}
        if len(ends) > 1 or len(starts) > 1:
            raise EvidenceError("Incompatible reporting dates")
