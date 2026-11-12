# Multi-company HTML testing plan

Prepared November 11, 2026. This is a proposed implementation and execution plan. No downloader or batch runner was implemented, and no new batch analysis was run while writing it.

## Recommended first milestone

Use six fixed FY2025 annual filings, review their expected answers, and run the same cases through the existing pipeline. Begin serially. Establish correctness before adding repetition or concurrency.

You should not need to download all the filings yourself. I recommend writing a small manifest-driven downloader around the existing SEC client and filing loader. Browser downloads are a fallback for individual blocked sources, rather than a prerequisite for the whole test.

There are three distinct questions:

1. Can the program select the right financial evidence and calculate the right answer across different filings?
2. When the evidence is missing or unsuitable, does it stop for the right reason?
3. Does repeated local execution remain stable, bounded and auditable?

Keep acquisition failures separate from analysis failures. An HTTP 403 says nothing about the financial pipeline's correctness.

## 1. Filings to use

Freeze the fiscal year and accession rather than resolving “latest” during every run. Fiscal 2025 does not mean every company's year ends in December, nor that the filing was submitted in calendar 2025.

| Company | Fiscal year end | Accession | Primary HTML and reason for inclusion | Local availability |
|---|---|---|---|---|
| Apple, AAPL | 2025-09-27 | `0000320193-25-000079` | [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm): retained development baseline. | Existing `evaluation/fixtures/apple_2025_10k.html`; register its actual bytes/hash. |
| Tesla, TSLA | 2025-12-31 | `0001628280-26-003952` | [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/1318605/000162828026003952/tsla-20251231.htm): known duplicate labels in consolidated and VIE contexts. | Existing `artifacts/tesla-current-ratio/tsla-20251231.htm`; explicitly mark it as a public mirror retaining inline XBRL. |
| Microsoft, MSFT | 2025-06-30 | `0000950170-25-100235` | [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm): additional statement layout and June fiscal year. | Acquire. |
| Amazon, AMZN | 2025-12-31 | `0001018724-26-000004` | [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/1018724/000101872426000004/amzn-20251231.htm): another layout with consolidated and segment disclosures. | Acquire. |
| Walmart, WMT | 2025-01-31 | `0000104169-25-000021` | [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/104169/000010416925000021/wmt-20250131.htm): January fiscal year and detailed revenue/segment presentations. | Acquire. |
| NVIDIA, NVDA | 2025-01-26 | `0001045810-25-000023` | [FY2025 10-K](https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm): non-calendar fiscal year and another balance-sheet/income-statement layout. | Acquire. |

The four new primary filing links above were checked through web lookup when preparing this plan. Their local download availability still needs testing. Apple and Tesla have already informed development; report them separately from first-pass results for the four new companies. Six companies form a pilot, not a broad market accuracy benchmark.

Start with one annual filing per company. The intended comparisons use FY2025/FY2024; inspect the actual statement columns to confirm coverage before labelling cases. Download older filings only for an explicit supporting-filing test or a genuinely missing period. Do not silently add supporting filings when a case is intended to test abstention.

If manual downloads are needed, download the four primary HTML documents for Microsoft, Amazon, Walmart and NVIDIA from this table. Save the document HTML, not the SEC search/index page, inline viewer shell, PDF, copied text or a screenshot. Register the resulting file's actual hash and acquisition method. A browser-saved page may differ from SEC's original bytes and must be identified as such.

## 2. Downloader design

Proposed new module: `evaluation/acquire_corpus.py`. Proposed input: `evaluation/cases/pilot_manifest.json`. These do not exist yet.

The manifest will list ticker, CIK, form, accession, expected fiscal year/end date, primary SEC URL, and any already available local source. The script will:

1. Register/reuse an existing verified local file when available.
2. Acquire missing files using the existing `SECClient`/`load_filing` behavior, with shared pacing across the batch. Use sequential requests, bounded retries and server retry guidance. The present client timer is instance-local, so merely looping over new clients does not establish a shared limit.
3. Validate HTTP response, HTML content, company/form/year identity and expected financial-statement content. Detect error pages rather than saving them as filings. Record whether inline XBRL is retained; never silently treat a converted version as the original layout.
4. Save raw bytes and a completed manifest containing canonical SEC URL, actual download URL, accession, timestamp, local path, SHA-256, byte count, acquisition method and status.
5. Resume without redownloading verified successes. Record blocked/missing items individually and produce a precise list of files requiring a browser download.

Configure `FFA_SEC_USER_AGENT` with an identifiable contact through the environment or local `.env` before SEC acquisition. Do not place credentials or contact values in the tracked manifest or summary report. This is an existing application requirement; see [SEC access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

Our direct Tesla download returned HTTP 403. A proper contact configuration is necessary for the existing client, but it does not guarantee that this environment can download every SEC URL. Stop/reduce attempts on blocking or throttling. If a mirror is needed, record its actual source and check identity, values and retained XBRL context against SEC. Source variants receive distinct hashes and case identities; do not silently substitute them in a frozen benchmark.

After acquisition, all analysis cases use local HTML. A missing or changed file fails the case preflight; replay does not fetch a replacement.

## 3. Cases and independent expected answers

Proposed typed case definitions: `evaluation/cases.py`, with case data in `evaluation/cases/pilot_cases.json`. Store review labels outside runtime pipeline schemas.

For every answerable case, independently inspect the source statement before scoring program output. Record the correct consolidated component rows, fiscal periods/dates, raw amounts, scales/currency, source references, expected numeric answer, unit and comparison direction. Freeze whether “revenue” means the reported consolidated revenue total for that source; do not opportunistically switch between segment sales, net sales and a total including other income to make a result pass.

Compute expected results separately from the application's calculator using those reviewed inputs. For ratio changes, compare each year's ratio as well as their difference and relative percentage change. Record explicit tolerances and compare unrounded values; proposed tolerances are `1e-8` absolute for ratio units and `1e-6` for percent/percentage-point results, reviewed before the first run. Check selected evidence and units as well as the final number.

A matching number from the wrong row is still wrong. `SUCCESS` is a program status, not an independent correctness grade. An abstention is correct only when the source review establishes the requested support is absent, ambiguous or outside the supported task.

## 4. First-pass test matrix

The core metrics for all six companies are:

- `revenue_growth`, FY2025 versus FY2024.
- `operating_margin_change`, FY2025 versus FY2024.
- `current_ratio_change`, FY2025 versus FY2024.

Review source coverage before finalizing expectations. An economically answerable source that the current parser fails to read is an unexpected abstention/failure to complete, rather than being relabelled “correctly insufficient.”

| Group | Planned runs | What it isolates |
|---|---:|---|
| Explicit formulas, agents disabled | 6 companies × 3 metrics = 18 | Real FinBERT, eligibility, deterministic concept checks and arithmetic. No Planner, Verifier or Corrector Agent calls. |
| Same formulas, agents enabled | 18 | Same explicit plans; Planner Agent bypassed, Verifier Agent reviews eligible selections, Corrector Agent runs only if recovery is needed. |
| Free-text current-ratio comparison | 6 | Planner Agent maps the question to `current_ratio_change` with the explicit years; then normal verification/recovery/calculation. |
| Missing-period negative cases, both modes | 6 cases × 2 modes = 12 | Each case requests periods independently confirmed absent, without supporting-source opt-in. Expect early `INSUFFICIENT_EVIDENCE`, no calculation and no model review calls. |
| Controlled recovery cases | 2 | On two companies, deliberately promote an existing structurally eligible wrong-concept row in the test retriever. Keep actual source facts and normal agents. Verify rejection, Corrector Agent recovery where possible, and re-verification of a replacement. |
| **First-pass total** | **56** | Count by mode/group/company, not as one undifferentiated accuracy percentage. |

Use a fixed free-text question template such as “How did the current ratio change from FY2024 to FY2025?” across companies, with the selected filing supplying entity context. Do not vary prompt wording while comparing the early filter or verifier across sources.

The two recovery tests are explicitly labelled fault injections. They establish recovery behavior and do not count as natural retrieval accuracy. If ordinary cases succeed without correction, that does not test the Corrector Agent. Existing synthetic regression tests remain a separate source of boundary-condition coverage.

## 5. How execution will work

Proposed new module: `evaluation/batch_runner.py`.

The main batch will call `Pipeline.run` directly. Streamlit and the CLI already call this same backend; the batch will use the same settings, real FinBERT and real local agent model. A fresh `Pipeline` instance per request keeps request state separate, while the existing process-level encoder cache can be reused. This avoids manual UI repetition and makes every case reproducible.

Run one case at a time initially. Record model name/digest, encoder revision, mode, config fingerprint, Git revision and working-tree source hash, parser/prompt/formula versions, Python/package versions, source hash and cache condition. The current working tree contains uncommitted implementation changes, so recording only Git HEAD would be insufficient.

Checkpoint each completed case and allow resume only for matching case/source/code/config identities. Add a case deadline and a batch time/call budget. Use an isolated worker when a hard timeout is required; the parent records an aborted/timed-out case even if the child cannot finish its audit. A timeout is a runner outcome, not a new LangGraph financial status.

Start with three smoke cases to check labels, output capture and actual local runtime before scheduling the full matrix. Correctness runs may warm caches for later modes; do not interpret such mode timings as a fair speed comparison. Keep cold-start measurements separate and label the cache/model residency conditions.

Real model timings depend on role calls, context length, retries and residency. The retained Tesla run took about 42 seconds for two Verifier Agent calls; this is a sizing observation, not a runtime guarantee. Estimate the remaining batch duration after the first smoke cases rather than promising a fixed completion time.

## 6. Streamlit checks

Use Streamlit for a few interface spot checks after backend execution: one known Apple or Tesla case, one new-company case, and one missing-period case. Confirm source/metric/period entry, agent toggle, progress, result, warning and audit display agree with backend runs using the same inputs/settings. These checks validate UI integration; they do not replace the batch corpus results.

If computer/browser control is available, I can perform these checks. It was unavailable during the earlier Tesla investigation, so do not assume UI automation will work. If it remains unavailable, run the existing Streamlit integration tests and provide three exact manual UI cases. Report GUI spot checks as pending until actually observed, independently of completed backend tests.

## 7. Results and failure records

Proposed generated layout; `artifacts/` is already ignored by Git:

```text
artifacts/multi-company/<batch_id>/
  manifest.json          # Frozen source and experiment identities
  cases.jsonl            # One completed/aborted case attempt per line
  summary.csv            # Readable case-level comparison table
  aggregate.json         # Counts and timings by company, metric and mode
  report.md              # Findings, limits and highest-priority failures
```

Keep existing per-request `audit.json` and evidence artifacts. The batch table links to them, rather than replacing them. Controlled fixtures and reviewed case definitions can be tracked under `evaluation/`; generated filings, logs and local audits remain under ignored artifacts. The downloader will not commit them automatically.

Each case record should contain:

| Category | Fields |
|---|---|
| Identity | Batch/case/attempt ID; source/accession/hash; fiscal years; metric/question; agent mode; code/config/model identities. |
| Program outcome | Actual final status, numeric result, period intermediates, comparison/direction, units, selected evidence IDs, warnings, errors. |
| Independent assessment | Expected status/inputs/result/units; evidence correctness; numeric error; grade and review note. |
| Execution | Duration by stage; Planner/Verifier/Corrector call counts separately; correction rounds; expansions; eligible/rejected counts and failed-check reasons; retries/cache condition; timeout or cancellation details. |
| Traceability | Audit and evidence artifact paths; acquisition method; reference statements used for the expected answer. |

Use grades such as `CORRECT_ANSWER`, `WRONG_ANSWER`, `CORRECT_ABSTENTION`, `UNEXPECTED_ABSTENTION`, `OPERATIONAL_ERROR`, `TIMEOUT` and `UNREVIEWED`. Never treat an unreviewed case as correct. For a successful answer, record evidence correctness and arithmetic correctness separately.

Extend `evaluation/metrics.py` or add a typed scorer: its present helper is insufficient for this report, including the missing-tolerance comparison hazard and a direction check that should not be applied indiscriminately to positive single-period ratios. Keep expected outputs in evaluation code, never pass them into agent/runtime payloads.

Report answer coverage, correct answers among answered cases, correct answers among independently answerable cases, correct/incorrect abstentions, and operational failures with counts and denominators. Break them down by company/metric/mode and distinguish known development companies from new companies. Include p50/p95 timings and agent calls; show individual durations and sample count where a group is too small for a meaningful percentile.

## 8. Repeated-run stress phase

After reviewing the first-pass results, select eight fixed cases: six independently answerable current-ratio cases plus two confirmed missing-period cases. Run each five additional times with agents enabled: 40 additional requests, bringing this pilot to 96 planned requests. If a core case is not independently answerable, replace it deliberately and document the subset; do not quietly remove a program failure from the report.

Measure status/number/evidence consistency, agent calls/retries, durations, cache reuse, audit completeness and process memory trend across repetitions. Sample process memory with a platform-appropriate method, and label any estimated or unavailable memory measurement. A warm-cache repetition phase does not measure cold-start performance.

Stop and record repeated operational failure, invalid output, corrupt cache/audit or an exceeded run budget. Record the number of planned, completed and aborted cases rather than leaving an apparently complete report. Add concurrency only as a later experiment after measuring local memory headroom; the encoder already serializes inference with a lock, and multiple processes can duplicate model memory.

This stress phase targets the local application, not SEC servers. It replays saved HTML and does not redownload filings.

## 9. Delivery order and decision criteria

1. Implement manifest acquisition/local-file registration and test resume, invalid HTML and blocked-download behavior.
2. Review source facts and freeze expected outputs for the six-company pilot.
3. Implement the serial runner/scorer and test them with existing doubles, then execute three live smoke cases.
4. Execute and review the 56 first-pass requests. Classify failures as acquisition, parsing/period/context extraction, retrieval, Planner Agent, Verifier Agent, Corrector Agent, final guard, calculator or persistence.
5. Execute the 40 repeated-run requests and the limited Streamlit checks. Publish the result table and failure report.
6. Turn confirmed issues into small fixes with regression cases. Report results before and after fixes separately. Once new-company cases inform a fix, they become development evidence; reserve new companies for the next held-out assessment.

The first milestone succeeds when the inputs and labels are frozen, every scheduled case is accounted for, correct answers use the right evidence, expected abstentions occur for the right reasons, and observed failures are reproducible from saved sources/configuration. It does not require reporting 100% success. A specific, well-traced failure is a useful result of this work.

Later expansion can add other industries, a bank as an explicit unsupported-layout/concept control, older supporting filings, and converted-HTML variants. Review each source before deciding which tasks should be answerable. Do not multiply files and formulas before the pilot runner and independent scoring are reliable.
