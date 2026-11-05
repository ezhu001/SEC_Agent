"""Transparent offline doubles. These do not estimate model performance."""
from financial_filing_agent.schemas.task import TaskPlan
from financial_filing_agent.config.financial_concepts import CONCEPTS
from financial_filing_agent.config.formulas import FORMULAS
from financial_filing_agent.retrieval.lexical_retriever import lexical_signals


def task(formula="revenue_growth", periods=None):
    spec = FORMULAS[formula]
    return TaskPlan(status="READY", formula_id=formula, required_components=list(spec.components),
        required_periods=periods or (["FY2025", "FY2024"] if spec.periods == 2 else ["FY2025"]),
        expected_statement_types={c: CONCEPTS[c][0] for c in spec.components},
        retrieval_queries={c: c.replace("_", " ") for c in spec.components})


class ScriptedDecoder:
    version = {"name": "scripted-offline-double", "digest": "not-a-model"}
    def __init__(self, scenario="success"):
        self.scenario, self.calls = scenario, []

    def complete(self, role, system, payload, schema):
        if role == "planner":
            answer = task("inventory_growth" if self.scenario == "missing" else "revenue_growth").model_dump()
        elif role == "verifier":
            good = payload["proposed_evidence"]["label"] == "Total net sales"
            answer = {"verdict": "PASS" if good else "FAIL", "error_type": "none" if good else "wrong_line_item", "confidence": 0.9, "reason": "Scripted concept check for control-flow demonstration",
                      "findings": [] if good else [{"check": "concept_match", "evidence_field": "label", "evidence_quote": payload["proposed_evidence"]["label"], "reason": "Cost of sales is not revenue"}]}
        else:
            candidate = next((r for r in payload["available_candidates"] if r["label"] == "Total net sales"), None)
            answer = {"decision": "REPLACE" if candidate else "NO_VALID_EVIDENCE", "evidence_id": candidate["evidence_id"] if candidate else None, "confidence": 0.9, "reason": "Scripted recovery"}
        if role == "verifier":
            from evaluation.review_double import review_checks
            answer["checks"] = review_checks(payload, answer["findings"])
        self.calls.append({"role": role, "request": payload, "output": answer, "seconds": 0})
        return schema.model_validate(answer)


class DemoRetriever:
    def __init__(self, scenario="success"):
        self.scenario = scenario

    def rank(self, rows, component, periods, query):
        ranked = []
        for row in rows:
            lexical, exact, xbrl = lexical_signals(row, component)
            score = 0.95 if self.scenario == "recovery" and row.label == "Total cost of sales" else 0.8 if row.label == "Total net sales" else 0.5
            ranked.append({"evidence_id": row.evidence_id, "label": row.label, "fusion_score": score,
                "signals": {"finbert": score, "lexical": lexical, "exact_label": exact, "xbrl": xbrl,
                    "statement": row.statement == CONCEPTS[component][0], "periods": all(any(f.period == p for f in row.facts) for p in periods), "numeric": bool(row.facts)}})
        ranked.sort(key=lambda r: -r["fusion_score"])
        return ranked, {"candidate_count": len(rows), "mode": "scripted-offline-double"}
