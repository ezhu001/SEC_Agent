"""Live local-model demonstrations; B is a controlled notebook-style retrieval stress."""
import argparse
import json
from pathlib import Path
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.models.finbert import get_finbert
from financial_filing_agent.retrieval.hybrid_retriever import HybridRetriever
from financial_filing_agent.services.pipeline import Pipeline
from .fixtures import APPLE_HTML


class NotebookStressRetriever:
    def __init__(self, settings):
        self.settings = settings.model_copy(update={"lexical_weight": 0, "xbrl_weight": 0})
        s = self.settings
        self.real = HybridRetriever(lambda: get_finbert(s.finbert_model, s.finbert_revision, s.finbert_device, s.token_limit, s.batch_size), s)

    def rank(self, rows, component, periods, query):
        pool = [r for r in rows if r.label in {"Total net sales", "Total cost of sales"}]
        return self.real.rank(pool, component, periods, "total net sales company revenue")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["success", "recovery", "missing", "all"], default="all")
    args = parser.parse_args()
    settings = Settings(artifact_dir=Path("artifacts/live-demo"))
    output = {}
    for name in (["success", "recovery", "missing"] if args.scenario == "all" else [args.scenario]):
        question = "How did total net sales change from FY2024 to FY2025?" if name != "missing" else "How did total net sales change from FY2019 to FY2020?"
        retriever = NotebookStressRetriever(settings) if name == "recovery" else None
        result = Pipeline(settings, retriever=retriever).run(question, str(APPLE_HTML))
        output[name] = {"mode": "live Qwen and FinBERT; recovery uses controlled two-row stress",
            "status": result["final_status"], "calculation": result["calculation_result"],
            "verifications": result["verification_results"], "corrections": result["correction_count"],
            "expansions": result["expanded_search_count"], "audit_path": result["audit_path"]}
        print(json.dumps({name: output[name]}, indent=2), flush=True)
    Path("artifacts/live-demo").mkdir(parents=True, exist_ok=True)
    from financial_filing_agent.services.cache import atomic_json
    atomic_json(Path("artifacts/live-demo") / (args.scenario + "-summary.json"), output)


if __name__ == "__main__":
    main()
