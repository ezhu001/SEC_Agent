"""Offline control-flow demonstrations, explicitly using test doubles, not live model claims."""
import json
from pathlib import Path
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.services.pipeline import Pipeline
from evaluation.doubles import ScriptedDecoder, DemoRetriever


def main():
    settings = Settings(artifact_dir=Path("artifacts/demo"))
    source = Path("evaluation/fixtures/demo.html")
    results = {}
    for name in ("success", "recovery", "missing"):
        question = "Revenue growth FY2025 versus FY2024" if name != "missing" else "Inventory growth FY2025 versus FY2024"
        result = Pipeline(settings, ScriptedDecoder(name), DemoRetriever(name)).run(question, str(source))
        results[name] = {"status": result["final_status"], "calculation": result["calculation_result"],
            "corrections": result["correction_count"], "expansions": result["expanded_search_count"],
            "audit_path": result["audit_path"], "mode": "offline scripted decoder and retrieval"}
    print(json.dumps(results, indent=2))
    assert [r["status"] for r in results.values()] == ["SUCCESS", "SUCCESS", "INSUFFICIENT_EVIDENCE"]


if __name__ == "__main__":
    main()
