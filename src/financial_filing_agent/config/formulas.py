from dataclasses import dataclass


@dataclass(frozen=True)
class Formula:
    components: tuple[str, ...]
    periods: int
    unit: str
    description: str

FORMULAS = {
    "revenue_growth": Formula(("revenue",), 2, "percent", "(new revenue - old revenue) / old revenue * 100"),
    "operating_margin": Formula(("operating_income", "revenue"), 1, "percent", "operating income / revenue * 100"),
    "operating_margin_change": Formula(("operating_income", "revenue"), 2, "percentage points", "new operating margin - old operating margin"),
    "current_ratio": Formula(("current_assets", "current_liabilities"), 1, "ratio units", "current assets / current liabilities"),
    "current_ratio_change": Formula(("current_assets", "current_liabilities"), 2, "ratio units", "new current ratio - old current ratio"),
    "gross_margin": Formula(("gross_profit", "revenue"), 1, "percent", "gross profit / revenue * 100"),
    "gross_margin_change": Formula(("gross_profit", "revenue"), 2, "percentage points", "new gross margin - old gross margin"),
    "rd_intensity": Formula(("research_and_development", "revenue"), 1, "percent", "research and development / revenue * 100"),
    "inventory_growth": Formula(("inventory",), 2, "percent", "(new inventory - old inventory) / old inventory * 100"),
    "accounts_receivable_growth": Formula(("accounts_receivable",), 2, "percent", "(new receivables - old receivables) / old receivables * 100"),
}


def registered_plan(formula_id, periods):
    """Construct the full dependency contract without a model decision."""
    from ..schemas.task import TaskPlan
    from .financial_concepts import CONCEPTS
    if formula_id not in FORMULAS:
        raise ValueError("Unregistered formula")
    spec = FORMULAS[formula_id]
    if not periods or len(periods) != spec.periods or len(set(periods)) != spec.periods:
        return TaskPlan(status="NEEDS_INPUT", notes=f"{formula_id} requires {spec.periods} explicit fiscal year(s).")
    import re
    if not all(re.fullmatch(r"FY\d{4}", p) for p in periods):
        return TaskPlan(status="NEEDS_INPUT", notes="Specify fiscal periods as FYyyyy, for example FY2025 FY2024.")
    return TaskPlan(status="READY", formula_id=formula_id,
        required_components=list(spec.components), required_periods=sorted(periods, reverse=True),
        expected_statement_types={c: CONCEPTS[c][0] for c in spec.components},
        retrieval_queries={c: f"{CONCEPTS[c][1][0]} required for {formula_id.replace('_', ' ')}" for c in spec.components},
        notes="Registered formula selected explicitly; planning arithmetic is not delegated to a model.")
