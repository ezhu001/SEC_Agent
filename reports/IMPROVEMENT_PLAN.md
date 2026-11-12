# Financial Filing Agent: Improvement Plan

Date: November 11, 2026
Scope: planning only; no application changes, model downloads, or SEC requests performed for this document.

## Recommendation

The next milestone should be a reliable, measurable local workflow across multiple companies. Prioritize local-model diagnostics, earlier evidence eligibility checks, and a reproducible batch benchmark. Expand financial features only after this benchmark identifies actual gaps.

Your teammate's suggestions are a good direction, with two adjustments based on the current code:

1. Qwen already connects to a local Ollama service. Configure and diagnose that connection before considering a new backend.
2. Ticker-based HTML acquisition already exists. Extend it with manifest-driven batch acquisition and replay instead of creating another downloader.

I interpret “测 dimension” as checking monetary units, percentages, currencies, reporting periods, and XBRL context dimensions such as business segments. These are related but distinct checks. If your teammate meant embedding-vector dimensions, that would instead be a small retrieval/cache integrity check; it would not replace financial evidence validation.

## What is already implemented

These observations come from source inspection, rather than a new live execution or accuracy evaluation.

| Area | Current behavior | Remaining opportunity |
|---|---|---|
| Local Qwen | `OllamaDecoder` posts to the configured Ollama `/api/chat`; defaults are localhost and `qwen2.5:latest`. | Make missing server/model and configuration mismatches easy to diagnose. |
| Configuration | `Settings` reads `FFA_` variables and `.env`; explicit configuration files can pin research settings. | Separate flexible local experiments from reproducible benchmark configurations. |
| Evidence checks | `check_inputs` runs before retrieval; `assess_concept` invokes mechanical checks before Qwen verification. | Filter structurally invalid rows before embedding and prevent invalid proposals from reaching Qwen/recovery. |
| Final safeguards | Guards and the Python calculator enforce provenance, periods, units, currency compatibility, and verified selections. | Preserve these checks after introducing an early filter. |
| SEC acquisition | `SECClient.resolve` accepts ticker/CIK/accession; `load_filing` caches and hashes HTML. | Collect a fixed corpus once, with provenance and resumable batch acquisition. |
| Evaluation | Scripted routing demos, Apple-focused live demos, regression tests, audit records, timing and decoder-call counts exist. | Add independent multi-company ground truth, batch execution, and reliable aggregate scoring. |

Relevant sources: [settings](../src/financial_filing_agent/config/settings.py), [decoder](../src/financial_filing_agent/models/local_decoder.py), [pipeline](../src/financial_filing_agent/services/pipeline.py), [validation](../src/financial_filing_agent/tools/validation.py), [SEC client](../src/financial_filing_agent/tools/sec_client.py), [loader](../src/financial_filing_agent/tools/filing_loader.py), [evaluation metrics](../evaluation/metrics.py).

## Priority 1: Make the local Qwen setup predictable

### Rationale

The code already uses the same local API on Windows and macOS. Replacing agent logic to accommodate a different machine would create unnecessary differences. Most local migration work should be configuration, diagnostics, and a small compatibility test.

### Implementation

- Continue using `FFA_OLLAMA_URL` and `FFA_DECODER_MODEL`. Use a model that fits the actual machine; compare `qwen2.5:3b` against a larger available model on the same cases before selecting a default. Smaller models may improve latency while weakening evidence review.
- Extend the existing `--status` path into a preflight report: server reachable, exact configured model available, resolved digest, Qwen enabled/disabled, FinBERT revision/device, and artifact-directory writability. Avoid printing SEC contact details or complete environment contents.
- Offer an explicit opt-in generation probe that asks the configured decoder for a tiny schema-valid result. A successful tags request alone does not establish that structured generation works. Ordinary status checks should remain cheap and should not automatically download models.
- Distinguish connection failure, absent model, timeout, malformed response, and schema/contract failure. Keep operational failures as `ERROR`; do not convert them into financial missing-evidence claims.
- Treat an endpoint as an HTTP service address. A local model file path is not interchangeable with `FFA_OLLAMA_URL`. If the desired runtime is actually a different serving protocol, add an adapter only after confirming its API and structured-output support.
- Save a dedicated local benchmark configuration with the actual model digest, encoder revision, prompts, budgets, and runtime versions. Leave `config/research.json` intact; explicitly constructed settings from that file can take precedence over local environment preferences.
- Separate retry policy for transport failures from structured-output repair. The current decoder shares one loop and validation-feedback behavior across both. Bound both policies and test their total call budget before changing defaults.

### Files and verification

Existing files: `models/local_decoder.py`, `config/settings.py`, `cli.py`, `ui/streamlit_app.py` under `src/financial_filing_agent/`, plus `README.md` and `.env.example` if instructions change. Proposed new tests: `tests/test_decoder_preflight.py`.

Mock server-down, missing-model, malformed JSON, HTTP failure, timeout, and successful schema validation. Follow with one opt-in live filing run. Preserve the existing `--no-qwen` behavior: no decoder calls and explicit formula/period requirements.

**Acceptance:** a new developer can identify their selected model and resolve startup failures from one status report; one real local run saves the model/configuration identity and audit. No automatic model substitution when a pinned digest differs.

## Priority 2: Reject incompatible evidence earlier

### Rationale

An LLM cannot repair a percentage masquerading as a monetary amount, missing fiscal years, or a segment-only value when the task needs consolidated totals. Rejecting these candidates early saves embedding and decoder work and makes failures easier to explain.

The present implementation already checks some of this before Qwen. The specific gap is that `HybridRetriever.rank` embeds the supplied pool before applying its signals, and the Qwen-enabled verification branch can still call Qwen after a deterministic concept assessment fails. This proposal moves eligibility ahead of expensive work rather than merely moving the final guard node.

### Implementation

1. Extract reusable structural checks from `guard` into a helper in `tools/validation.py`. Return a typed result with evidence ID, eligibility status, and stable reason codes. Keep verification-dependent checks, such as `reverified_selection`, in the final guard; they cannot truthfully pass before verification.
2. Evaluate each component's candidate pool for source membership, expected statement, one fact per requested year, finite values, monetary units/basis, consolidated context, instant versus duration, annual duration where known, and within-row currency consistency. Check required denominator periods using the existing formula rules.
3. Distinguish definite incompatibility from incomplete metadata. For example, an explicit segment dimension is incompatible with a consolidated-only task; missing metadata requires a documented conservative policy. Do not let absent context silently imply consolidated totals, and do not drop potentially valid rows based only on unfamiliar labels or low lexical similarity.
4. Apply the shared eligibility helper before initial ranking, expanded ranking, and correction selection. Preserve every parsed row in the evidence artifact, with rejection reasons in the audit. Expansion must not resurrect a structurally rejected candidate.
5. Preserve a cheap period inventory before retrieval. Extend its diagnostics to distinguish missing periods, structurally incompatible candidates, and unresolved concepts. `FOUND` currently signals a candidate match, not final accepted evidence. Exhausted eligible pools should produce `INSUFFICIENT_EVIDENCE` with specific reasons; parsing/runtime failures remain `ERROR`.
6. Keep Qwen focused on unresolved accounting meaning and source context. Explicit formula runs can avoid the planner; free-text runs may still need a planner call before component-specific eligibility is known.
7. Retain post-verification guards and final `compatible_inputs` checks. Currency/date compatibility across numerator and denominator requires the actual selected combination. Do not reject an entire filing merely because some alternative rows are incompatible.

### Financial policy to preserve

- Monetary gross-profit amounts and percentage gross-margin rows are different evidence types, even when labels resemble each other.
- Explicit XBRL dimensions represent context, not units. Keep rejecting segment-specific facts for consolidated formulas; do not sum segments to manufacture a total.
- Normalize reported scales once. Revalidate mixed scales and signs with source-backed fixtures.
- Preserve the current common-table monetary-basis rule for dimensionless results when ISO currency is unspecified. Do not infer USD from `$` or require ISO currency in a way that breaks the converted-HTML regression cases.
- Preserve the existing independently checked gross-profit identity. Do not extend it into deriving absent reported facts in this milestone.
- All final arithmetic stays in registered Python calculators.

### Files and verification

Existing files: `tools/validation.py`, `tools/input_inventory.py`, `tools/concept_validation.py`, `services/pipeline.py`, `schemas/state.py`, and, if diagnostics change, `services/progress.py` and UI components. Add a graph node only if a separate stage materially improves audit visibility; an internal helper may be the smaller change. Proposed new tests: `tests/test_early_eligibility.py`.

Test wrong units, explicit/typed segment contexts, missing and duplicate periods, instant/duration mismatches, mixed currency, scale normalization, zero denominators, and ambiguous metadata. Include a higher-ranked invalid row beside a lower-ranked valid row. Use a retriever spy and forbidden decoder to assert that invalid candidates are excluded before embedding and verification, including after expansion/correction. Repeat the converted gross-margin and supporting-filing regressions.

**Acceptance:** definite structural failures reach neither embedding nor Qwen review; empty eligible pools explain their failure; supported baseline answers remain correct; no invalid candidate returns through recovery. Report decoder calls and latency before/after on the same fixtures rather than promising a speedup in advance.

## Priority 3: Build a frozen HTML corpus and batch runner

### Rationale

More Apple examples alone will not establish generality. A useful benchmark varies company, table layout, fiscal calendar, terminology, and failure conditions. Separating acquisition from execution also prevents network variability from obscuring local model behavior.

### A. Corpus acquisition

Proposed new module: `evaluation/acquire_corpus.py`. Reuse `SECClient.resolve` and `load_filing`; do not duplicate SEC URL construction or parsing.

- Accept a small input manifest of ticker/CIK and preferably explicit accession. Resolve “latest” only during acquisition, then freeze the selected accession, form, primary-document URL, company identity, acquisition timestamp, content hash, and local cache path in an output manifest.
- Add a batch wrapper around acquisition, with per-item results, restart/resume support, bounded retries, and a summary of failures. Cache ticker/submission metadata within acquisition so repeated identifiers do not repeatedly fetch the same mapping.
- Serialize acquisition initially. The current rate timer belongs to each `SECClient` instance, while `load_filing` creates clients; it does not provide a shared batch limit. Introduce a shared client/limiter for the acquisition stage, and test pacing across consecutive filings and retry paths. Respect server retry instructions and stop/reduce acquisition on repeated throttling. Do not stress-test SEC servers.
- Keep acquired HTML content-addressed under the existing artifact cache. Store a reviewable manifest and labels separately from generated run artifacts. Detect HTML error pages and source-identity/form mismatches before admitting a file to the corpus.
- Replay benchmarks using local paths with acquisition disabled. Hash mismatch or missing file must fail clearly rather than silently fetching a replacement.

Start with six filings for a pilot, then expand to approximately 24 filings from 12 companies, ideally two annual filings each. Select layout and accounting variety deliberately; some sectors will intentionally have unsupported concepts. Review form, company identity, actual fiscal periods, and input coverage instead of forcing every formula to succeed.

Use four companies for development and eight for a held-out set. Keep all filings and HTML variants of one company in one split. Existing Apple development material stays in development. Candidate counts are targets, not a claim that a corpus has already been collected.

### B. Case definitions and independent answers

Proposed files: `evaluation/cases.py` and `evaluation/corpus_manifest.json`.

Each case should record a case ID, split, local filing/hash, formula or question, explicit periods, expected terminal outcome, and independently reviewed component evidence. For answerable cases, retain raw reported inputs, source table/row/context references, expected numeric result, output unit, and explicit tolerance. For intentionally unanswerable cases, record the missing or incompatible requirement.

Ground truth must be reviewed from the source HTML before evaluating program output. Do not use Qwen or the program's own selected rows as the sole label source. Freeze labels before held-out evaluation; after tuning on a held-out failure, report that case as development and reserve fresh cases for the next assessment.

Begin with about 30 pilot cases, then roughly 120 cases across the larger corpus. Cover all ten registered formulas where source evidence supports them, plus missing-period, ambiguous-label, incompatible-unit/context, and zero-denominator cases. Mark unsupported tasks explicitly rather than treating every abstention as correct.

### C. Execution and scoring

Proposed new module: `evaluation/batch_runner.py`. Invoke `Pipeline.run` with a fresh pipeline per request, reusing existing process-cached encoder behavior where appropriate. Preserve each run's audit path.

- Run serially first, with a manifest hash/configuration identity, per-case checkpoint, aggregate JSON and CSV output, and resume keyed by case + source + configuration + code revision. Hash local code changes as well as recording Git revision when the working tree is dirty.
- Distinguish expected final outcomes from operational failures and unexpected abstentions. Continue after one case fails; preserve partial results.
- Add a bounded per-case deadline using an isolated worker where hard termination is needed. A parent must record timed-out/aborted cases even if the child cannot finish its audit. Keep persistent serial workers for warm-cache measurements; identify worker restarts rather than labeling them warm runs.
- Compare deterministic formula mode (`--no-qwen`, real FinBERT) with Qwen verification on the same explicit plans. Evaluate natural-language planning separately so planner errors are not confused with verification errors. Scripted demos remain control-flow checks.
- Fix/extend `evaluation/metrics.py` first: a missing tolerance must not cause a comparison error; units and evidence selection must be scored; positive single-period ratios must not be called an “increase” just because their value is positive. Score change direction only for change/growth tasks, with explicit expected labels and tolerances.

Report correct answers / answered cases, correct answers / answerable cases, expected abstentions, unexpected abstentions, operational errors, and wrong answers separately. Show denominators, counts, and breakdowns by formula/company/split/mode. Include evidence correctness, unit correctness, p50/p95 latency, decoder calls, retries, expansions, cache behavior, and measured peak memory where available. A `SUCCESS` flag is not ground-truth correctness.

**Acceptance:** the frozen corpus replays without network access, resumes without losing completed cases, and produces case-level evidence plus an aggregate report. All pilot labels receive manual review. No held-out accuracy claim relies on scripted models or historical mixed-run audit counts.

## Priority 4: Test reliability and resource limits locally

### Rationale

Accuracy evaluation and load testing answer different questions. A correct serial answer does not prove stable repeated execution, and a fast incorrect answer is not useful.

After the pilot runner works, perform these separate experiments:

| Experiment | Method | What to measure |
|---|---|---|
| Cold versus warm | Use disposable cache namespaces; separate app-cache state from resident model state and first-time downloads. | Parsing, embedding, model-load, generation, and total time. |
| Repeated serial use | Repeat a fixed subset 20–50 times; keep source/config hashes fixed. | Status consistency, numeric/evidence stability, memory growth, cache reuse, audit completeness. |
| Controlled local concurrency | Increase workers from one to two only after measuring available memory. | Throughput, p95 latency, timeouts, cache-write behavior, memory pressure. |
| Failure injection | Mock Ollama timeout/malformed JSON, cache corruption, write denial, missing files, and cancellation. | Bounded retries, correct `ERROR` classification, preserved results, resumability. |

The FinBERT encoder has an inference lock, so concurrency may queue rather than speed up retrieval. Separate processes can duplicate model memory. Do not promise GPU/MPS acceleration or introduce a worker pool until measurements justify it. Shared-cache stress must first verify write integrity; avoid concurrent SEC acquisition.

Existing tests already cover several audit write failures and progress behavior. Extend those tests instead of recreating them. Add retrieval embedding-width/finiteness/cache-shape validation only as a focused integrity improvement if stress tests expose a gap.

**Acceptance:** every scheduled case has a terminal or explicitly aborted runner record; final successful runs have readable audits; errors remain bounded; repeated serial execution has no unexplained memory growth trend. Establish performance thresholds from the measured local baseline rather than inventing hardware-independent targets.

## Delivery sequence

Effort estimates assume one developer and exclude model downloads, SEC availability, and substantial labeling effort.

| Stage | Deliverable | Estimated effort | Exit condition |
|---|---|---|---|
| 0 | Baseline: record environment, run existing tests, retain representative local audits. | Half a day | Known baseline; failures documented before changes. |
| 1 | Local-model preflight and setup instructions. | Half to one day | Clear configuration report and one live smoke run. |
| 2 | Shared early eligibility checks with regression coverage. | One to two days | Invalid facts filtered; baseline answers preserved. |
| 3 | Scoring fixes, acquisition manifest, serial runner, six-file pilot. | Two to three days plus labeling | Reviewed pilot runs offline and resumes. |
| 4 | Larger held-out corpus and local stress experiments. | Two to four days plus labeling | Per-case report, reliability results, prioritized failure list. |

Keep changes reviewable: one change for preflight, one for eligibility, one for acquisition, one for runner/scoring, then a benchmark report. Freeze an evaluation baseline before tuning retrieval weights or model sizes. Classify failures as acquisition, parsing/context extraction, retrieval, planning, semantic review, calculation, or persistence; use that distribution to choose the next fix.

## Verification commands available today

Run from the repository root. These are existing commands; they were not executed as part of writing this plan.

```bash
# Fast regressions for the main proposed behavior changes.
.venv/bin/python -m pytest tests/test_qwen_modes.py tests/test_metric_workflow.py tests/test_sources.py -q

# Full existing regression suite after the targeted checks pass.
.venv/bin/python -m pytest -q

# Diagnose the configured local decoder; this contacts local Ollama when enabled.
.venv/bin/python -m financial_filing_agent.cli --status

# Existing local-filing smoke run; FinBERT may download on first use.
.venv/bin/python -m financial_filing_agent.cli \
  --source evaluation/fixtures/apple_2025_10k.html \
  --formula revenue_growth --periods FY2025 FY2024 --no-qwen
```

The proposed acquisition and batch modules do not exist yet; their interfaces should be documented when implemented. No commands in this document should be interpreted as having downloaded a corpus or established new benchmark results.

## Defer until the benchmark shows a need

Defer additional agents, a new vector database, a UI rewrite, PDF/OCR support, automatic cross-filing fact merging, broad formula expansion, and alternative model-serving backends. These introduce new failure modes and make it harder to evaluate the three improvements above. Parser/context fixes discovered by the benchmark remain in scope as small, source-backed corrections with regression fixtures and parser-cache version changes when needed.

The milestone is complete when local setup is diagnosable, structurally incompatible evidence is rejected early, and a frozen multi-company corpus produces reproducible case-level correctness and reliability reports.
