"""Serial live evaluation with isolated workers, append-only results and explicit grades."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import time
import uuid

from evaluation.cases import Case, score
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.services.cache import atomic_json


def code_identity():
    digest = hashlib.sha256()
    for root in (Path("src"), Path("evaluation")):
        for path in sorted(root.rglob("*.py")):
            digest.update(str(path).encode())
            digest.update(path.read_bytes())
    revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    return {"git_revision": revision, "working_source_sha256": digest.hexdigest()}


def memory(pid):
    try:
        rss = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=True)
        return round(int(rss.stdout.strip()) / 1024, 2)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def worker(connection, overrides):
    os.environ["HF_HUB_OFFLINE"] = "1"
    from financial_filing_agent.services.pipeline import Pipeline

    class FaultRetriever:
        def __init__(self, real):
            self.real = real

        def rank(self, rows, component, periods, query):
            ranked, diagnostics = self.real.rank(rows, component, periods, query)
            if component == "current_assets":
                wrong = next((r for r in ranked if r["label"].lower() == "total assets"), None)
                if wrong:
                    ranked = [wrong] + [r for r in ranked if r is not wrong]
                    diagnostics["controlled_fault"] = {"promoted_id": wrong["evidence_id"], "wrong_concept": "total assets instead of current assets"}
            return ranked, diagnostics

    while True:
        request = connection.recv()
        if request is None:
            return
        try:
            settings = Settings(**{**overrides, "qwen_enabled": request["agents"], "sec_user_agent": ""})
            pipeline = Pipeline(settings)
            if request["fault"]:
                pipeline.retriever = FaultRetriever(pipeline.retriever)

            def progress(event):
                connection.send({"kind": "progress", "event": event,
                                 "audit_path": str(pipeline.audit.directory / "audit.json")})

            result = pipeline.run(request["question"], request["source"], request["periods"],
                                  formula_id=request["formula"], on_progress=progress)
            result.pop("config", None)
            calls = pipeline.decoder.calls
            connection.send({"kind": "result", "result": result,
                             "role_attempts": dict(Counter(c["role"] for c in calls)),
                             "role_generation_calls": dict(Counter(c["role"] for c in calls if c.get("attempt", 0) == 0)),
                             "transport_retries": sum(c.get("attempt", 0) > 0 for c in calls)})
        except Exception as exc:
            connection.send({"kind": "result", "result": {"final_status": "ERROR", "errors": [
                {"node": "batch_worker", "type": type(exc).__name__, "message": str(exc)}]}, "role_attempts": {},
                "role_generation_calls": {}, "transport_retries": 0})


def write_reports(output, cases, records, status):
    counts = Counter(r["grade"] for r in records)
    by_company, by_group, by_mode = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for r in records:
        by_company[r["ticker"]][r["grade"]] += 1
        by_group[r["group"]][r["grade"]] += 1
        by_mode[r["mode"]][r["grade"]] += 1
    aggregate = {"status": status, "planned": len(cases), "completed": len(records), "counts": dict(counts),
                 "by_company": dict(by_company), "by_group": dict(by_group), "by_mode": dict(by_mode),
                 "incorrect_case_ids": [r["case_id"] for r in records if r["grade"] == "WRONG_ANSWER"],
                 "other_failed_case_ids": [r["case_id"] for r in records if r["grade"] not in {"CORRECT_ANSWER", "CORRECT_ABSTENTION", "WRONG_ANSWER"}]}
    atomic_json(output / "aggregate.json", aggregate)
    columns = ["case_id", "ticker", "group", "mode", "grade", "incorrect_result", "actual_status", "expected_value", "actual_value",
               "numeric_error", "scoring_version", "strict_label_grade", "label_reviews", "seconds", "role_attempts", "corrections", "expansions", "worker_rss_mb", "reasons", "audit_path"]
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in record.items()})
    (output / "summary.csv").write_text(stream.getvalue(), encoding="utf-8")
    lines = ["# Multi-company live test results", "", f"Status: **{status}**. Recorded {len(records)} of {len(cases)} planned requests.", "",
             "Real FinBERT and local agent model. Gold labels were frozen before execution. Acquisition is outside analysis timing.",
             "Apple/Tesla are development companies; other companies are first-pass pilot material. Recovery fault injections are separate from natural accuracy.",
             "Expected missing-period abstentions are separate from unexpected abstentions on answerable sources.", "",
             "## Grades", "", "| Grade | Count |", "|---|---:|"]
    lines += [f"| {grade} | {number} |" for grade, number in sorted(counts.items())]
    lines += ["", "## Failed cases", "", "WRONG_ANSWER explicitly marks an incorrect answer, evidence selection, unit, or controlled-recovery outcome.", ""]
    failures = [r for r in records if r["grade"] not in {"CORRECT_ANSWER", "CORRECT_ABSTENTION"}]
    for record in failures:
        lines += [f"- **{record['grade']} — {record['case_id']}**: " + "; ".join(record["reasons"])]
    if not failures:
        lines.append("No failures recorded so far; this is not a claim about unfinished requests.")
    lines += ["", "## Every recorded request", "", "| Case | Assessment | Program status | Seconds |", "|---|---|---|---:|"]
    for r in records:
        grade = r["grade"] if r["grade"] in {"CORRECT_ANSWER", "CORRECT_ABSTENTION"} else f"**{r['grade']}**"
        lines.append(f"| {r['case_id']} | {grade} | {r['actual_status']} | {r['seconds']:.2f} |")
    lines += ["", "Details: `summary.csv`, append-only `cases.jsonl`, per-case snapshots, `progress.json`, and each request's audit path.",
              "Generation calls and transport attempts are recorded separately. Timing comparisons include cache/residency effects and are not a controlled speed benchmark.",
              "Worker RSS samples are current application-process resident memory; they exclude Ollama's separate process and GPU allocations.",
              "Streamlit GUI spot checks are reported separately and are not implied by backend completion."]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source = Path(args.cases)
    cases = [Case.model_validate(c) for c in json.loads(source.read_text())["cases"]]
    settings = Settings(sec_user_agent="", artifact_dir=Path("artifacts/multi-company/pipeline"))
    from financial_filing_agent.models.local_decoder import OllamaDecoder
    decoder = OllamaDecoder(settings)
    status = decoder.status()
    if not status["available"]:
        raise RuntimeError("Configured local agent model is unavailable; no cases were started")
    settings.expected_decoder_digest = status["digest"]
    identity = {**code_identity(), "cases_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "config_hash": settings.fingerprint(), "model_digest": status["digest"]}
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        if json.loads(manifest_path.read_text())["identity"] != identity:
            raise ValueError("Resume refused: code, cases, configuration or model changed. Use a new output directory.")
    else:
        atomic_json(manifest_path, {"identity": identity, "started_at": datetime.now(timezone.utc).isoformat(),
                                   "model": settings.decoder_model, "planned": len(cases), "case_deadline_seconds": args.case_seconds,
                                   "request_ids": [c.case_id for c in cases], "corpus_manifest": "artifacts/multi-company/corpus/manifest.json"})
    journal = output / "cases.jsonl"
    records = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()] if journal.exists() else []
    done = {r["case_id"] for r in records}
    session = uuid.uuid4().hex[:12]
    context = multiprocessing.get_context("spawn")
    process, connection = None, None
    started, completed_here, batch_status = time.monotonic(), 0, "RUNNING"
    write_reports(output, cases, records, batch_status)
    try:
        for case in cases:
            if case.case_id in done:
                continue
            if args.limit is not None and completed_here >= args.limit:
                batch_status = "CHECKPOINT_LIMIT"
                break
            if time.monotonic() - started > args.max_batch_seconds:
                batch_status = "BATCH_TIME_LIMIT"
                break
            stamp, case_started = datetime.now(timezone.utc).isoformat(), time.monotonic()
            print(f"START {len(records)+1}/{len(cases)} {case.case_id}", flush=True)
            request = case.request()
            latest = {"case_id": case.case_id, "started_at": stamp, "stage": "preflight"}
            atomic_json(output / "progress.json", latest)
            message = None
            try:
                source_valid = hashlib.sha256(Path(case.source).read_bytes()).hexdigest() == case.source_hash
            except OSError:
                source_valid = False
            if not source_valid:
                message = {"result": {"final_status": "ERROR", "errors": [{"type": "SourceHashMismatch", "message": "Frozen source changed"}]}}
            else:
                if process is None or not process.is_alive():
                    if process is not None:
                        process.join()
                        connection.close()
                    connection, child = context.Pipe()
                    process = context.Process(target=worker, args=(child, settings.model_dump(mode="json")))
                    process.start()
                    child.close()
                connection.send(request)
                while time.monotonic() - case_started < args.case_seconds:
                    if connection.poll(1):
                        try:
                            event = connection.recv()
                        except EOFError:
                            break
                        if event["kind"] == "result":
                            message = event
                            break
                        latest.update({"stage": event["event"]["node"], "phase": event["event"]["phase"], "audit_path": event["audit_path"]})
                        atomic_json(output / "progress.json", latest)
                    if not process.is_alive():
                        break
            elapsed = time.monotonic() - case_started
            if message is None:
                timed_out = elapsed >= args.case_seconds
                assessment = {"grade": "TIMEOUT" if timed_out else "OPERATIONAL_ERROR", "reasons": ["Worker exceeded case deadline" if timed_out else "Worker exited without a result"]}
                result = {"final_status": "ABORTED", "audit_path": latest.get("audit_path")}
                message = {}
                if process is not None:
                    process.terminate()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join()
            else:
                result = message["result"]
                assessment = score(case, result)
            record = {"case_id": case.case_id, "ticker": case.ticker, "group": case.group, "mode": case.mode,
                      "scoring_version": case.scoring_version,
                      "formula": case.formula, "development_company": case.development_company,
                      "started_at": stamp, "worker_session": session, "source_hash": case.source_hash,
                      "actual_status": result["final_status"], **assessment, "incorrect_result": assessment["grade"] == "WRONG_ANSWER",
                      "seconds": elapsed, "role_attempts": message.get("role_attempts", {}),
                      "role_generation_calls": message.get("role_generation_calls", {}), "transport_retries": message.get("transport_retries", 0),
                      "corrections": result.get("correction_count", 0), "expansions": result.get("expanded_search_count", 0),
                      "worker_rss_mb": memory(process.pid) if process is not None and process.is_alive() else None,
                      "audit_path": result.get("audit_path"), "errors": result.get("errors", []), "warnings": result.get("warnings", []),
                      "accepted_evidence": result.get("accepted_evidence", {}), "calculation": result.get("calculation_result"),
                      "timings": result.get("timings", {}), "eligibility": {c: ds[0].get("eligibility", {}) for c, ds in result.get("retrieval_diagnostics", {}).items()}}
            atomic_json(output / "cases" / f"{case.case_id}.json", {"record": record, "result": result})
            with journal.open("a", encoding="utf-8") as log:
                log.write(json.dumps(record, allow_nan=False) + "\n")
                log.flush()
                os.fsync(log.fileno())
            records.append(record)
            completed_here += 1
            done.add(case.case_id)
            write_reports(output, cases, records, "RUNNING")
            atomic_json(output / "progress.json", {**latest, "phase": "recorded", "grade": record["grade"], "completed": len(records), "planned": len(cases)})
            print(f"RESULT {case.case_id} {record['grade']} status={record['actual_status']} seconds={elapsed:.2f} reasons={record['reasons']}", flush=True)
        else:
            batch_status = "COMPLETE"
    finally:
        if process is not None and process.is_alive():
            connection.send(None)
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        write_reports(output, cases, records, batch_status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="evaluation/cases/pilot_cases.json")
    parser.add_argument("--output", default="artifacts/multi-company/pilot-2026-11-11")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-seconds", type=int, default=300)
    parser.add_argument("--max-batch-seconds", type=int, default=7200)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
