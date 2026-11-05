from typing import Literal
from pydantic import Field, model_validator
from .evidence import Record


class VerificationFinding(Record):
    check: Literal["concept_match", "statement_match", "required_periods", "monetary_unit", "reporting_scope", "formula_role"]
    evidence_field: Literal["label", "statement", "facts", "nearby_context"]
    observation: Literal["quote", "missing_field"] = "quote"
    evidence_quote: str = Field(max_length=300)
    reason: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def grounded_observation(self):
        if self.observation == "quote" and not self.evidence_quote:
            raise ValueError("A quote observation requires a nonempty verbatim excerpt")
        if self.observation == "missing_field" and self.evidence_quote:
            raise ValueError("A missing-field observation must not invent a quote")
        return self


class VerificationCheck(VerificationFinding):
    status: Literal["PASS", "FAIL", "UNCERTAIN"]


class Verification(Record):
    verdict: Literal["PASS", "FAIL", "UNCERTAIN"]
    error_type: Literal["none", "wrong_line_item", "wrong_statement", "wrong_period", "unit_or_value_problem", "wrong_formula_role", "insufficient_evidence", "wrong_context"]
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(max_length=700)
    findings: list[VerificationFinding] = Field(default_factory=list, max_length=6,
        description="Derived by Python from non-PASS check observations; may be omitted by the decoder")
    checks: list[VerificationCheck] = Field(max_length=6)

    @model_validator(mode="before")
    @classmethod
    def aggregate_check_observations(cls, value):
        if not isinstance(value, dict) or not value.get("checks"):
            return value
        data = dict(value)
        checks = [c.model_dump() if isinstance(c, Record) else c for c in data["checks"]]
        negative = [c for c in checks if c.get("status") != "PASS"]
        data["verdict"] = "FAIL" if any(c.get("status") == "FAIL" for c in checks) else "UNCERTAIN" if negative else "PASS"
        data["findings"] = [{k: v for k, v in c.items() if k != "status"} for c in negative]
        error_map = {"concept_match": "wrong_line_item", "statement_match": "wrong_statement",
            "required_periods": "wrong_period", "monetary_unit": "unit_or_value_problem",
            "reporting_scope": "wrong_context", "formula_role": "wrong_formula_role"}
        data["error_type"] = next((error_map[name] for name in error_map if any(c.get("check") == name for c in negative)),
                                  "insufficient_evidence" if negative else "none")
        return data

    @model_validator(mode="after")
    def consistent(self):
        if (self.verdict == "PASS") != (self.error_type == "none"):
            raise ValueError("Verdict and error type inconsistent")
        if self.verdict == "PASS" and self.findings:
            raise ValueError("PASS cannot contain blocking findings")
        if self.verdict != "PASS" and not self.findings:
            raise ValueError("FAIL/UNCERTAIN requires an allowed check and a source-grounded finding")
        return self


class Correction(Record):
    decision: Literal["REPLACE", "EXPAND_SEARCH", "NO_VALID_EVIDENCE"]
    evidence_id: str | None
    confidence: float = Field(ge=0, le=1)
    reason: str

    @model_validator(mode="after")
    def consistent(self):
        if (self.decision == "REPLACE") != (self.evidence_id is not None):
            raise ValueError("Replacement requires an ID; other decisions require null")
        return self


class Calculation(Record):
    formula_id: str
    formula: str
    value: float
    unit: str
    direction: Literal[-1, 0, 1]
    inputs: dict[str, dict[str, float]]
    intermediates: dict[str, float]
    comparison: dict = Field(default_factory=dict)
