# Multi-company HTML stress-test results

Completed November 11, 2026. **All 96 scheduled requests were executed and recorded.** The application logic, prompts, source files and experiment code stayed frozen during execution. No application fix was applied to improve these results.

## Outcome counts

| Assessment | First pass | Repeated requests | Total |
|---|---:|---:|---:|
| CORRECT_ANSWER | 25 | 15 | 40 |
| CORRECT_ABSTENTION | 10 | 10 | 20 |
| WRONG_ANSWER | 3 | 0 | 3 |
| OPERATIONAL_ERROR | 18 | 15 | 33 |
| UNEXPECTED_ABSTENTION | 0 | 0 | 0 |
| TIMEOUT | 0 | 0 | 0 |

A program `SUCCESS` was not accepted as proof of correctness. All three `WRONG_ANSWER` requests returned `SUCCESS` and were independently flagged by their source inputs and numeric outputs. Errors emitted no derived financial answer.

## Explicitly incorrect answers

| Case | Expected | Actual | Unit | Audit |
|---|---:|---:|---|---|
| **WMT-operating_margin_change-deterministic — INCORRECT** | 0.141925151828 | 0.147523687628 | percentage points | [audit](../artifacts/multi-company/pipeline/runs/0cc844eab4374bf9bad3097907476d0d/audit.json) |
| **WMT-revenue_growth-agents — INCORRECT** | 5.0700096432 | 4.96407769861 | percent | [audit](../artifacts/multi-company/pipeline/runs/e935fede38e1407ebaf4e7daa83baf24/audit.json) |
| **WMT-revenue_growth-deterministic — INCORRECT** | 5.0700096432 | 4.96407769861 | percent | [audit](../artifacts/multi-company/pipeline/runs/98464e09325040298a47500453f75490/audit.json) |

All three selected Walmart **Net sales** (FY2025/FY2024: 674,538/642,637 million) instead of the predeclared **Total revenues** basis (680,985/648,125 million), which includes membership and other income. These reported amounts are in [Walmart's SEC 10-K](https://www.sec.gov/Archives/edgar/data/104169/000010416925000021/wmt-20250131.htm). The arithmetic is coherent on a net-sales basis; it is incorrect relative to this frozen total-revenue test definition. A net-sales-based margin can be a separate named metric, so the fix should make the revenue basis explicit rather than declare every net-sales calculation invalid.

In the agent-enabled growth case, Python had already marked `concept_match` and `formula_role` resolved using the registered revenue alias. The Verifier Agent only reviewed reporting scope and returned PASS; it did not independently settle the two coexisting revenue bases.

## Operational failures

| Node / exception | Requests | Observation |
|---|---:|---|
| `build_evidence` / `ValueError` | 14 | Every Microsoft request failed on a parenthesized numeric token, before retrieval or verification. |
| `verify` / `VerifierContractError` | 19 | Invalid source quotes or consolidated-scope assertions failed the executable review contract. |

Microsoft source metadata also recorded June 30, **2026**, despite the explicit source date `June 30,2025`. The installed date parser reproduced this shift. The numeric exception happens first; fix and test both numeric parsing and explicit filing-date parsing before treating Microsoft as supported. The new corpus acquisition checker uses strict explicit-date parsing, so it verified and retained the actual FY2025 file without changing the application loader.

For the natural Apple and Walmart current-ratio cases, initial ranking selected the correct current-liabilities row. The Verifier Agent then falsely rejected or questioned its consolidated scope while quoting the consolidated balance-sheet heading. The Corrector Agent returned no valid alternative after that correct row was excluded. A later expanded proposal reached a citation-format contract error. This is not simply an initial retrieval-ranking failure.

Both controlled recovery cases failed during the first verifier review/repair, before reaching a Corrector Agent call. They therefore do not demonstrate successful end-to-end recovery. Detailed traces are in the [diagnosis note](../artifacts/multi-company/pilot-2026-11-11/diagnosis.md).

## By company, including repeats and controlled cases

| Company | Correct answers | Correct abstentions | Wrong answers | Operational errors |
|---|---:|---:|---:|---:|
| AAPL | 5 | 7 | 0 | 8 |
| AMZN | 11 | 2 | 0 | 1 |
| MSFT | 0 | 0 | 0 | 14 |
| NVDA | 12 | 2 | 0 | 0 |
| TSLA | 11 | 7 | 0 | 2 |
| WMT | 1 | 2 | 3 | 8 |

Apple and Tesla are known development inputs. Microsoft, Amazon, Walmart and NVIDIA are new-company pilot inputs. The table includes correlated repetitions and must not be read as a market-wide accuracy estimate.

## First-pass interpretation

Excluding the two controlled faults, the first pass contained **54 natural requests**: 42 source-answerable tasks and 12 missing-period controls. The program emitted 28 answers; 25 were correct and 3 were incorrect. That is **25/28 (89.3%) correctness among emitted answers**, but only **25/42 (59.5%) correct completion of answerable tasks**. Ten of twelve missing-period controls correctly abstained; two hit the Microsoft parser error.

The 56-request first pass comprised 36 explicit-formula requests across two modes, 6 free-text questions, 12 missing-period controls across two modes, and 2 controlled retrieval faults. Three metrics were covered: revenue growth, operating-margin change and current-ratio change, FY2025 versus FY2024. See the [first-pass tables](../artifacts/multi-company/pilot-2026-11-11/first-pass-summary.md).

## Agent roles actually exercised

| Role | Generation calls | Observation |
|---|---:|---|
| Planner Agent | 6 | All six free-text cases returned the expected formula and fiscal years. Five later failed elsewhere; a correct task plan is not an end-to-end success. |
| Verifier Agent | 121 | Count includes contract-repair generations. False scope rejection and source-quote formatting were material failures. |
| Corrector Agent | 17 | Natural recovery paths were exercised; the two deliberately faulted cases stopped upstream before correction. |

Generation calls and physical attempts were equal in this batch; no decoder transport retries were recorded. Deterministic cases bypassed all three model roles. Expected explicit-formula missing-period controls called no model, except that Microsoft failed even earlier at parsing.

## Repetition results

Forty requests repeated eight scenarios five times each. All eight groups retained the same terminal grade, numerical result where present, and selected-evidence IDs. This includes stable failure, not only stable success.

| Repeated scenario | Five outcomes |
|---|---|
| AAPL missing periods | CORRECT_ABSTENTION: 5 |
| AAPL current-ratio change | OPERATIONAL_ERROR: 5 |
| AMZN current-ratio change | CORRECT_ANSWER: 5 |
| MSFT current-ratio change | OPERATIONAL_ERROR: 5 |
| NVDA current-ratio change | CORRECT_ANSWER: 5 |
| TSLA missing periods | CORRECT_ABSTENTION: 5 |
| TSLA current-ratio change | CORRECT_ANSWER: 5 |
| WMT current-ratio change | OPERATIONAL_ERROR: 5 |

Successful repeated ratio requests (n=15) had median **34.39s** and descriptive p95 **38.55s**. Case execution summed to 41.1 minutes; elapsed time including the smoke checkpoint was 43.3 minutes. Cache/model residency and request content affect these figures; this was not a controlled speed comparison.

Application-worker RSS sampled after requests reached 581.7 MiB. Ollama was sampled separately 67 times at 15-second intervals during the late repetition phase; maximum sampled summed process RSS was 2539.2 MiB. These are RSS samples, not continuous peaks, unique physical RAM, GPU allocations or proof of no memory leak. No worker timeout occurred.

## Validation and interface checks

- **122 automated tests passed; 3 skipped** (opt-in live encoder tests and a Windows-only test). The 96 live requests separately used real FinBERT and the configured local agent model.
- Three Streamlit AppTest replay checks passed for Tesla, Amazon and missing periods: form submission, mode selection, status, numeric display or warning. They reused recorded real backend outputs and did not make extra model calls.
- Browser GUI control was checked and unavailable. No browser GUI observations are claimed. Exact optional steps are saved in [manual UI cases](../artifacts/multi-company/pilot-2026-11-11/manual-ui-cases.md).
- **96 unique case records, 96 per-case snapshots and 96 unique readable audits** reconciled. Working source hash and served model digests matched the frozen identities.
- All 43 emitted answers received additional independent comparison-field checks, including relative percentage change. Only the same three already flagged Walmart cases mismatched their references.
- Runtime audits were checked for gold-answer fields; expected answers were confined to the evaluation side.

## Sources and reproducibility

One FY2025 filing each for AAPL, TSLA, MSFT, AMZN, WMT and NVDA. Apple uses retained development HTML; the other five are labelled Barchart mirrors with inline XBRL retained. Canonical SEC URLs, actual download URLs, identity metadata and hashes are preserved. The 24 primary component rows / 48 amounts were independently checked against SEC statements and raw inline facts before analysis. No byte-for-byte equivalence with SEC downloads is claimed.

Model: `qwen2.5:3b`, digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`. Working source SHA-256: `147675edcd44be7fbe0712e7c1cbebfad2ba568b3e4741820e22d184e0d7ec7b`. Full experiment identity is in the [manifest](../artifacts/multi-company/pilot-2026-11-11/manifest.json).

## Recommended next fixes

1. Resolve revenue-basis ambiguity when Net sales and Total revenues coexist; make the selected basis explicit. This is the issue that emitted incorrect successful answers under the frozen policy.
2. Fix unmatched-parenthesis numeric handling and strict explicit filing-date parsing, then rerun Microsoft on the same retained file.
3. Prevent false semantic vetoes of well-supported consolidated rows and make source references robust without weakening provenance checks. Repeat the controlled recovery cases after that fix.

Apply fixes in a new batch. Preserve this baseline and report before/after results rather than overwrite failures.

## Saved records

- [Every request: CSV](../artifacts/multi-company/pilot-2026-11-11/summary.csv)
- [Append-only case journal](../artifacts/multi-company/pilot-2026-11-11/cases.jsonl)
- [Complete case report](../artifacts/multi-company/pilot-2026-11-11/report.md)
- [Aggregate counts](../artifacts/multi-company/pilot-2026-11-11/aggregate.json) and [analysis](../artifacts/multi-company/pilot-2026-11-11/analysis.json)
- [Audit and comparison validation](../artifacts/multi-company/pilot-2026-11-11/validation.json)
- [Frozen source manifest](../artifacts/multi-company/pilot-2026-11-11/corpus-manifest.snapshot.json), [references](../artifacts/multi-company/pilot-2026-11-11/references.snapshot.json) and [independent row checks](../artifacts/multi-company/pilot-2026-11-11/reference-review.snapshot.json)
- [UI checks](../artifacts/multi-company/pilot-2026-11-11/ui-checks.json) and [memory samples](../artifacts/multi-company/pilot-2026-11-11/ollama-memory.jsonl)

## Files added for this step

- `evaluation/acquire_corpus.py`: local registration, bounded downloads, explicit mirror provenance, checkpoints and hash checks.
- `evaluation/cases.py`: typed requests, independent arithmetic and evidence-aware scoring; gold excluded from worker requests.
- `evaluation/batch_runner.py`: serial persistent worker, deadlines, resumability, append-only journal, per-case records and live reports.
- `evaluation/cases/pilot_manifest.json`, `pilot_references.json`, `pilot_cases.json`: source definitions, reviewed amounts and frozen 96-request matrix.
- `tests/test_corpus_acquisition.py`, `tests/test_pilot_evaluation.py`: acquisition, grading, request-boundary and report checks.
- `evaluation/README.md`: commands and interpretation; this report and ignored generated experiment artifacts.

The existing application implementation was not modified in this testing step. Previously present working-tree changes remain part of the captured baseline.
