from typing import Literal, Annotated
from pydantic import Field, model_validator
from .evidence import Record
from ..config.formulas import FORMULAS


class TaskPlan(Record):
    calculation_tool: Literal["registered_python_calculator"] = "registered_python_calculator"
    comparison_policy: Literal["python_only"] = "python_only"
    status: Literal["READY", "NEEDS_INPUT", "UNSUPPORTED_TASK"]
    formula_id: str | None = None
    required_components: list[str] = Field(default_factory=list)
    required_periods: list[Annotated[str, Field(pattern=r"^FY\d{4}$")]] = Field(default_factory=list, description="Exact fiscal-year tokens such as FY2025 and FY2024, newest first; never date ranges or bare years")
    expected_statement_types: dict[str, str] = Field(default_factory=dict)
    retrieval_queries: dict[str, str] = Field(default_factory=dict)
    notes: str = ""

    @model_validator(mode="after")
    def allowlisted(self):
        if self.status != "READY":
            return self
        if self.formula_id not in FORMULAS:
            raise ValueError("Unregistered formula")
        formula = FORMULAS[self.formula_id]
        if set(self.required_components) != set(formula.components) or len(self.required_components) != len(formula.components):
            raise ValueError("Components must exactly match formula")
        if len(self.required_periods) != formula.periods or len(set(self.required_periods)) != formula.periods:
            raise ValueError("Explicit distinct fiscal periods required")
        import re
        if not all(re.fullmatch(r"FY\d{4}", p) for p in self.required_periods):
            raise ValueError("Use explicit FYyyyy periods")
        if self.required_periods != sorted(self.required_periods, reverse=True):
            raise ValueError("Periods must be newest first")
        from ..config.financial_concepts import CONCEPTS
        for c in formula.components:
            if self.expected_statement_types.get(c) != CONCEPTS[c][0] or not self.retrieval_queries.get(c):
                raise ValueError("Missing or inconsistent component metadata")
        return self
