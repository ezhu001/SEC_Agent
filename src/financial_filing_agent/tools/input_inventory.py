"""Deterministic component-by-period inventory before model verification."""
from ..retrieval.lexical_retriever import lexical_signals
from ..config.financial_concepts import CONCEPTS


def inventory(rows, plan):
    cells = []
    for component in plan.required_components:
        statement_rows = [r for r in rows if r.statement == CONCEPTS[component][0]]
        concept_rows = [r for r in statement_rows if any(lexical_signals(r, component)[1:])]
        for period in plan.required_periods:
            matches = [r for r in concept_rows if sum(f.period == period for f in r.facts) == 1]
            structural = [r for r in statement_rows if any(f.period == period for f in r.facts)]
            status = "FOUND" if matches else "NEEDS_VERIFICATION" if structural else "MISSING_PERIOD"
            cells.append({"component": component, "period": period, "status": status,
                          "evidence_ids": [r.evidence_id for r in matches]})
    return cells


def missing_periods(cells):
    return [cell for cell in cells if cell["status"] == "MISSING_PERIOD"]
