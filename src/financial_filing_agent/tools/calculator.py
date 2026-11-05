import math
from ..config.formulas import FORMULAS
from ..schemas.results import Calculation
from .validation import compatible_inputs, EvidenceError


def calculate(plan, accepted, verified_ids):
    formula = FORMULAS[plan.formula_id]
    if set(accepted) != set(formula.components):
        raise EvidenceError("Not all required components are accepted")
    if any(verified_ids.get(c) != row.evidence_id for c, row in accepted.items()):
        raise EvidenceError("Evidence was not verified after selection")
    compatible_inputs(accepted, plan.required_periods,
                      allow_currency_cancellation=formula.unit in {"percent", "percentage points", "ratio units"})
    inputs = {c: {p: next(f.value for f in row.facts if f.period == p) for p in plan.required_periods}
              for c, row in accepted.items()}
    intermediate = {}
    comparison = {}
    def divide(a, b):
        if b == 0:
            raise EvidenceError("Undefined calculation: zero denominator")
        return a / b
    if plan.formula_id.endswith("growth"):
        component = formula.components[0]
        new, old = [inputs[component][p] for p in plan.required_periods]
        value = divide(new - old, old) * 100
        monetary_unit = next(f.currency for f in accepted[component].facts if f.period == plan.required_periods[0]) or "monetary units (currency unspecified)"
        comparison = {"new_period": plan.required_periods[0], "old_period": plan.required_periods[1],
                      "new_value": new, "old_value": old, "absolute_change": new - old,
                      "relative_change_percent": value,
                      "period_value_unit": monetary_unit, "absolute_change_unit": monetary_unit}
    else:
        numerator, denominator = formula.components
        multiplier = 1 if plan.formula_id.startswith("current_ratio") else 100
        for p in plan.required_periods:
            intermediate[p] = divide(inputs[numerator][p], inputs[denominator][p]) * multiplier
        values = list(intermediate.values())
        value = values[0] - values[1] if formula.periods == 2 else values[0]
        if formula.periods == 2:
            comparison = {"new_period": plan.required_periods[0], "old_period": plan.required_periods[1],
                          "new_value": values[0], "old_value": values[1], "absolute_change": value,
                          "relative_change_percent": divide(value, values[1]) * 100 if values[1] != 0 else None,
                          "relative_change_note": None if values[1] != 0 else "Undefined: previous metric equals zero",
                          "period_value_unit": "ratio units" if plan.formula_id.startswith("current_ratio") else "percent",
                          "absolute_change_unit": formula.unit}
    if comparison:
        comparison["direction"] = "increase" if value > 0 else "decrease" if value < 0 else "unchanged"
    if not math.isfinite(value):
        raise EvidenceError("Nonfinite calculation")
    return Calculation(formula_id=plan.formula_id, formula=formula.description, value=value,
        unit=formula.unit, direction=1 if value > 0 else -1 if value < 0 else 0,
        inputs=inputs, intermediates=intermediate, comparison=comparison)
