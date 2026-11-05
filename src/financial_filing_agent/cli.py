import argparse
import json
from .config.settings import Settings
from .models.local_decoder import OllamaDecoder
from .services.pipeline import Pipeline
from .config.formulas import FORMULAS


def main():
    parser = argparse.ArgumentParser(description="Local SEC filing evidence workflow")
    parser.add_argument("--source", help="Local HTML/cache path, SEC URL, ticker, CIK, accession or ticker/accession")
    parser.add_argument("--question")
    parser.add_argument("--periods", nargs="+", help="Explicit FYyyyy periods, newest first")
    parser.add_argument("--config", help="Frozen settings JSON")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--full", action="store_true", help="Print full serializable state")
    parser.add_argument("--formula", choices=list(FORMULAS), help="Explicit registered metric; bypass model planning")
    parser.add_argument("--supporting-source", action="append", default=[], help="Same-company supplementary HTML/SEC source")
    parser.add_argument("--use-cached-filings", action="store_true", help="Opt in to same-company cached supporting filings")
    parser.add_argument("--no-qwen", action="store_true", help="Disable all Qwen roles; use metric menu/formula and deterministic concept validation")
    args = parser.parse_args()
    settings = Settings.from_file(args.config) if args.config else Settings()
    if args.no_qwen:
        settings = settings.model_copy(update={"qwen_enabled": False})
    if args.status:
        print(json.dumps(OllamaDecoder(settings).status() if settings.qwen_enabled else
                         {"qwen_enabled": False, "status": "disabled; no Ollama request made"}, indent=2))
        return
    if not args.source or (not args.question and not args.formula):
        parser.error("--source and either --question or --formula are required")
    result = Pipeline(settings).run(args.question or "", args.source, args.periods, formula_id=args.formula,
        supplementary_sources=args.supporting_source, use_cached_filings=args.use_cached_filings)
    print(json.dumps(result if args.full else {**result["final_response"], "audit_path": result["audit_path"], "timings": result["timings"]}, indent=2, ensure_ascii=False))
    if result["final_status"] == "ERROR":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
