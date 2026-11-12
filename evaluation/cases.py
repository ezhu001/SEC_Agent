"""Frozen pilot requests and independent scoring; gold never enters the runtime."""
import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from financial_filing_agent.services.cache import atomic_json


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    ticker: str
    group: Literal["formula", "planner", "missing_periods", "recovery", "repeat"]
    mode: Literal["agents", "deterministic"]
    formula: Literal["revenue_growth", "operating_margin_change", "current_ratio_change"]
    source: str
    source_hash: str
    periods: list[str] = Field(default_factory=lambda: ["FY2025", "FY2024"])
    expected_status: Literal["SUCCESS", "INSUFFICIENT_EVIDENCE"] = "SUCCESS"
    question: str = ""
    fault: bool = False
    reference: dict
    development_company: bool
    scoring_version: Literal["1", "2"] = "1"

    def request(self):
        # Deliberate allowlist: no expected inputs, labels or answers cross this boundary.
        return {"case_id": self.case_id, "source": self.source, "periods": self.periods,
                "question": self.question, "formula": None if self.group == "planner" else self.formula,
                "agents": self.mode == "agents", "fault": self.fault}


def expectations(case):
    """Independent arithmetic on reviewed source amounts, not the app calculator."""
    ref = case.reference
    periods = case.periods
    components = (["revenue"] if case.formula == "revenue_growth" else
                  ["operating_income", "revenue"] if case.formula == "operating_margin_change" else
                  ["current_assets", "current_liabilities"])
    inputs = {c: dict(zip(periods, (v * 1_000_000 for v in ref[c]))) for c in components}
    if case.formula == "revenue_growth":
        value = (ref["revenue"][0] / ref["revenue"][1] - 1) * 100
        metrics = {}
        unit = "percent"
    else:
        a, b = components
        multiplier = 100 if case.formula == "operating_margin_change" else 1
        metrics = {p: ref[a][i] / ref[b][i] * multiplier for i, p in enumerate(periods)}
        value = metrics[periods[0]] - metrics[periods[1]]
        unit = "percentage points" if multiplier == 100 else "ratio units"
    return {"value": value, "unit": unit, "inputs": inputs, "intermediates": metrics,
            "direction": 1 if value > 0 else -1 if value < 0 else 0,
            "tolerance": 1e-8 if unit == "ratio units" else 1e-6}


def close(actual, expected, tolerance):
    return isinstance(actual, (int, float)) and math.isfinite(actual) and abs(actual - expected) <= tolerance


def equivalent_facts(case, component, row):
    """Independent evaluation identity check; runtime assessments are not consulted."""
    expected = case.reference.get("fact_identities", {}).get(component, {})
    if row.get("filing_hash") != case.source_hash or case.reference.get("identity_source_sha256") != case.source_hash:
        return False
    keys = ("concept", "context_id", "entity_identifier", "entity_scheme", "unit", "currency", "scale",
            "start", "end", "instant", "dimensions", "value")
    for period in case.periods:
        reference = expected.get(period)
        facts = [f for f in row.get("facts", []) if f.get("period") == period]
        if not reference or reference.get("period") != period or len(facts) != 1 or any(not reference.get(k) for k in ("concept", "context_id", "entity_identifier", "entity_scheme", "currency")):
            return False
        if any(facts[0].get(k) != reference.get(k) for k in keys):
            return False
    return True


def score(case, result):
    status = result.get("final_status", "ERROR")
    if status == "ERROR":
        errors = result.get("errors", [])
        return {"grade": "OPERATIONAL_ERROR", "reasons": [
            f"{e.get('node', '')}: {e.get('type', '')}: {e.get('message', '')[:240]}" for e in errors] or ["Pipeline returned ERROR"]}
    if case.expected_status != "SUCCESS":
        correct = (status == case.expected_status and result.get("calculation_result") is None
                   and result.get("decoder_call_count", 0) == 0)
        return {"grade": "CORRECT_ABSTENTION" if correct else "WRONG_ANSWER",
                "reasons": [] if correct else ["Expected missing-period abstention without model calls or calculation"]}
    if status != "SUCCESS":
        return {"grade": "UNEXPECTED_ABSTENTION", "reasons": [f"Reviewed source supports an answer; received {status}"]}
    expected, reasons, label_reviews = expectations(case), [], {}
    calc = result.get("calculation_result") or {}
    if calc.get("formula_id") != case.formula:
        reasons.append("Wrong formula")
    if not close(calc.get("value"), expected["value"], expected["tolerance"]):
        reasons.append("Incorrect final numeric answer")
    if calc.get("unit") != expected["unit"] or calc.get("direction") != expected["direction"]:
        reasons.append("Wrong units or direction")
    if set(result.get("accepted_evidence", {})) != set(expected["inputs"]):
        reasons.append("Wrong accepted component coverage")
    for component, values in expected["inputs"].items():
        row = result.get("final_response", {}).get("evidence", {}).get(component, {})
        labels = [" ".join(x.lower().split()) for x in case.reference["labels"][component]]
        label_match = " ".join(row.get("label", "").lower().split()) in labels
        equivalent = equivalent_facts(case, component, row) if case.scoring_version == "2" else False
        label_reviews[component] = {"label_match": label_match, "fact_equivalent": equivalent,
                                    "selected_label": row.get("label")}
        if case.scoring_version == "2" and not equivalent:
            reasons.append(f"Wrong or missing reviewed fact identity for {component}")
        if (not label_match and not equivalent) or row.get("filing_hash") != case.source_hash:
            reasons.append(f"Wrong source/label for {component}")
        for i, (period, value) in enumerate(values.items()):
            if not close(calc.get("inputs", {}).get(component, {}).get(period), value, 0.5):
                reasons.append(f"Wrong calculator input: {component}/{period}")
            facts = [f for f in row.get("facts", []) if f.get("period") == period]
            if (len(facts) != 1 or not close(facts[0].get("value"), value, 0.5)
                    or facts[0].get("dimensions") or facts[0].get("unit") != "currency"
                    or facts[0].get("currency") != "USD" or facts[0].get("end") != case.reference["ends"][i]):
                reasons.append(f"Wrong evidence value/period/unit/scope: {component}/{period}")
    for period, value in expected["intermediates"].items():
        if not close(calc.get("intermediates", {}).get(period), value, expected["tolerance"]):
            reasons.append(f"Wrong intermediate metric for {period}")
    if case.fault and not result.get("correction_count", 0):
        reasons.append("Controlled recovery did not exercise correction")
    return {"grade": "WRONG_ANSWER" if reasons else "CORRECT_ANSWER", "reasons": reasons,
            "scoring_version": case.scoring_version, "label_reviews": label_reviews,
            "strict_label_grade": score(case.model_copy(update={"scoring_version": "1"}), result)["grade"] if case.scoring_version == "2" else ("WRONG_ANSWER" if reasons else "CORRECT_ANSWER"),
            "expected_value": expected["value"], "actual_value": calc.get("value"),
            "expected_unit": expected["unit"], "numeric_error": (calc["value"] - expected["value"]
                if isinstance(calc.get("value"), (int, float)) and math.isfinite(calc["value"]) else None)}


def build_cases(corpus, references):
    cases = []
    for filing in corpus["filings"]:
        if filing["status"] != "AVAILABLE":
            raise ValueError(f"Unavailable filing: {filing['ticker']}")
        ticker = filing["ticker"]
        base = {"ticker": ticker, "source": str(Path(filing["local_path"]).relative_to(Path.cwd())),
                "scoring_version": references.get("scoring_version", "1"),
                "source_hash": filing["sha256"], "reference": references["references"][ticker],
                "development_company": ticker in {"AAPL", "TSLA"}}
        for mode in ("deterministic", "agents"):
            for formula in ("revenue_growth", "operating_margin_change", "current_ratio_change"):
                cases.append(Case(**base, case_id=f"{ticker}-{formula}-{mode}", group="formula", mode=mode, formula=formula))
            cases.append(Case(**base, case_id=f"{ticker}-missing-{mode}", group="missing_periods", mode=mode,
                              formula="current_ratio_change", periods=["FY2010", "FY2009"], expected_status="INSUFFICIENT_EVIDENCE"))
        cases.append(Case(**base, case_id=f"{ticker}-planner", group="planner", mode="agents", formula="current_ratio_change",
                          question="How did the current ratio change from FY2024 to FY2025?"))
        if ticker in {"AAPL", "TSLA"}:
            cases.append(Case(**base, case_id=f"{ticker}-controlled-recovery", group="recovery", mode="agents", formula="current_ratio_change", fault=True))
        for repeat in range(1, 6):
            cases.append(Case(**base, case_id=f"{ticker}-ratio-repeat-{repeat}", group="repeat", mode="agents", formula="current_ratio_change"))
            if ticker in {"AAPL", "TSLA"}:
                cases.append(Case(**base, case_id=f"{ticker}-missing-repeat-{repeat}", group="repeat", mode="agents",
                                  formula="current_ratio_change", periods=["FY2010", "FY2009"], expected_status="INSUFFICIENT_EVIDENCE"))
    smoke = ["AAPL-current_ratio_change-agents", "TSLA-current_ratio_change-agents", "MSFT-current_ratio_change-agents"]
    return sorted(cases, key=lambda c: (0, smoke.index(c.case_id)) if c.case_id in smoke else (2 if c.group == "repeat" else 1, c.case_id))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="artifacts/multi-company/corpus/manifest.json")
    parser.add_argument("--references", default="evaluation/cases/pilot_references.json")
    parser.add_argument("--output", default="evaluation/cases/pilot_cases.json")
    args = parser.parse_args()
    corpus = json.loads(Path(args.corpus).read_text())
    references = json.loads(Path(args.references).read_text())
    cases = build_cases(corpus, references)
    for case in cases:
        assert hashlib.sha256(Path(case.source).read_bytes()).hexdigest() == case.source_hash
    atomic_json(Path(args.output), {"schema_version": 1, "reference_review": references["review_method"],
                                   "cases": [c.model_dump() for c in cases]})
    print(f"Frozen {len(cases)} cases: {sum(c.group != 'repeat' for c in cases)} first-pass and {sum(c.group == 'repeat' for c in cases)} repeats")


if __name__ == "__main__":
    main()
