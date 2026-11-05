import re
from ..config import prompts
from ..config.formulas import FORMULAS
from ..config.financial_concepts import CONCEPTS
from ..schemas.task import TaskPlan


def plan_task(decoder, question, metadata, periods=None):
    plan = decoder.complete("planner", prompts.PLANNER, {
        "question": question, "filing_metadata": metadata, "requested_periods": periods or [],
        "formula_registry": {k: {"components": v.components, "period_count": v.periods, "meaning": v.description} for k, v in FORMULAS.items()},
        "concepts": {k: {"statement": v[0], "role": k.replace("_", " ")} for k, v in CONCEPTS.items()},
    }, TaskPlan)
    if plan.status == "READY":
        question_periods = ["FY" + y for y in re.findall(r"\b(?:FY\s*)?(20\d{2})\b", question, re.I)]
        if periods and question_periods and set(periods) != set(question_periods):
            return TaskPlan(status="NEEDS_INPUT", notes="Question periods conflict with the explicit period input.")
        explicit = periods or question_periods
        if not explicit or set(explicit) != set(plan.required_periods):
            return TaskPlan(status="NEEDS_INPUT", notes="Specify the exact fiscal periods; the planner may not invent them.")
    return plan
