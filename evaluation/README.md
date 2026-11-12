# Multi-company live evaluation

The pilot uses frozen FY2025 HTML for AAPL, TSLA, MSFT, AMZN, WMT and NVDA. Expected inputs are independently reviewed source amounts in `cases/pilot_references.json`; no gold labels enter agent requests. The live runner tests the same `Pipeline.run` backend used by Streamlit.

Run from the repository root:

```bash
# Register existing files and acquire missing ones. Mirror fallback is explicit.
.venv/bin/python -m evaluation.acquire_corpus --allow-mirror

# Freeze 56 first-pass requests and 40 repeated requests.
.venv/bin/python -m evaluation.cases

# Execute three smoke requests, recording each outcome immediately.
HF_HUB_OFFLINE=1 .venv/bin/python -m evaluation.batch_runner --limit 3

# Resume remaining requests without replacing prior outcomes.
HF_HUB_OFFLINE=1 .venv/bin/python -m evaluation.batch_runner
```

Default corpus: `artifacts/multi-company/corpus/manifest.json`. Default batch: `artifacts/multi-company/pilot-2026-11-11/`. Use `--output` to select a new batch directory. Resume refuses changed source code, case definitions, settings or model digest. A recorded failure remains recorded; use a separate batch/attempt when rerunning after a fix.

Acquisition requires the existing identifiable SEC contact setting for direct SEC requests. Missing contact or download failure is recorded; explicitly enabled Barchart fallback is labelled in provenance. Replays use local paths only, verify hashes, disable SEC acquisition credentials, and set Hugging Face offline mode. Local Ollama must already provide the configured decoder model.

Case outputs include an append-only `cases.jsonl`, a per-case result snapshot, `summary.csv`, `aggregate.json`, `progress.json` and `report.md`. Incorrect `SUCCESS` results are marked `WRONG_ANSWER`; unexpected abstentions, errors and timeouts have separate failure grades. Expected missing-period abstentions must avoid both model calls and calculation. Recovery fault injections are marked separately and do not measure ordinary retrieval accuracy.

Agent calls and physical transport attempts are recorded separately by role. Case deadlines default to 300 seconds; the per-invocation batch budget defaults to 7200 seconds. A persistent isolated worker reuses the encoder across cases; a timed-out worker is terminated and restarted. Worker RSS records application-process memory and excludes Ollama/GPU allocations. Initial smoke execution and resume have separate worker sessions; timings include cache and residency effects.

The main result is a source-grounded correctness/reliability pilot, not a population accuracy estimate. Apple/Tesla are known development inputs. First-pass and repeated observations, agent-enabled and deterministic modes, negative cases and controlled faults must be reported separately. Existing scripted demos remain tests of control flow rather than live model accuracy.

Streamlit's UI is checked separately using integration tests and, where available, explicit GUI spot checks. A completed backend batch does not imply GUI observations were made.

## Version-2 fact-equivalence scoring

`cases/scope_references_v2.json` adds 48 raw XBRL fact identities from the previously reviewed primary rows. `review_fact_identities.py` independently extracts them from retained HTML and checks the old reviewed amounts, end dates, issuer, currency and dimensions. The runtime parser and its scope conclusions are not used to construct or grade these references. Evaluation identities and scoring versions are excluded by `Case.request()`.

Version 1 remains the default for old cases. Version 2 requires complete same-filing reviewed fact identity, including concept, context/entity, units/scale, values, fiscal dates and dimensions; it can accept a different display label for the same fact. `label_reviews` records label agreement and identity agreement separately. `strict_label_grade` retains a version-1 comparison. Matching values alone are insufficient; Walmart Net sales remains different from the reviewed Total revenues.

Generate cases and run in a new directory, preserving historical batches:

```bash
.venv/bin/python -m evaluation.cases --references evaluation/cases/scope_references_v2.json --output artifacts/multi-company/scope-v2/cases.json
HF_HUB_OFFLINE=1 .venv/bin/python -m evaluation.batch_runner --cases artifacts/multi-company/scope-v2/cases.json --output artifacts/multi-company/scope-v2
```

Optional independent reference regeneration must use a new path, since the builder refuses to overwrite files:

```bash
.venv/bin/python -m evaluation.review_fact_identities --output artifacts/reviewed-identities-check.json
```
