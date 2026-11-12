# Revenue-basis change and targeted replay

Completed November 12, 2026. **The revenue policy is implemented; Walmart's agent-enabled workflows still have unresolved Verifier failures.** This is a separate replay batch. The original 96-request baseline remains retained.

## Behavior changed

- Revenue labels are grouped into reported revenue totals and net sales in `src/financial_filing_agent/config/financial_concepts.py`.
- Registered revenue metrics prefer a separately reported, structurally supported consolidated revenue total. A supported XBRL tag on Net sales does not make it interchangeable with that total.
- Net sales remains supported when no separate reported revenue total is found for the requested years. Apple and Amazon retain their Total net sales inputs.
- A partial reported total does not permit switching to net sales for the missing year. Conflicting totals block acceptance; identical repeated totals remain usable. The application does not synthesize totals or choose the largest amount.
- The policy filters initial retrieval, expansion and correction candidates. Verification independently rejects a basis mismatch before a decoder call. Structural eligibility remains a separate check.
- Retrieval diagnostics retain rejected IDs and reasons. Concept assessments and the final response record the selected revenue basis.

The policy recognizes the configured normalized revenue-total labels. It is not a general solution for every custom label or financial statement hierarchy. A separate net-sales metric is not exposed by this change.

## Recorded real replay: nine requests

The unchanged case definitions, source hashes, reviewed reference amounts and scoring rules were reused from the pilot. Requests ran through the existing backend with real FinBERT and the configured local `qwen2.5:3b` service; deterministic cases made no agent calls. The application source identity stayed unchanged during this replay. The current tree also includes the preceding acceptance-guard simplification, so this is a regression comparison, not an isolated performance experiment.

| Case | Original grade | New grade | Result |
|---|---|---|---|
| Walmart revenue growth, deterministic | WRONG_ANSWER | CORRECT_ANSWER | **5.0700096432%**, using Total revenues. Previously 4.9640776986% using Net sales. |
| Walmart revenue growth, agents | WRONG_ANSWER | **UNEXPECTED_ABSTENTION — FAILED** | Correct Total revenues rows proposed, then falsely rejected by the Verifier. No financial answer emitted. |
| Walmart operating-margin change, deterministic | WRONG_ANSWER | CORRECT_ANSWER | **0.1419251518 percentage points**, using Total revenues. Previously 0.1475236876 points using Net sales. |
| Walmart operating-margin change, agents | OPERATIONAL_ERROR | **OPERATIONAL_ERROR — FAILED** | Verifier scope-quote contract error during operating-income review; did not reach successful revenue acceptance or calculation. |
| Apple revenue growth, deterministic | CORRECT_ANSWER | CORRECT_ANSWER | 6.4255117828%; Total net sales retained. |
| Apple revenue growth, agents | CORRECT_ANSWER | CORRECT_ANSWER | 6.4255117828%; Total net sales retained. |
| Amazon revenue growth, deterministic | CORRECT_ANSWER | CORRECT_ANSWER | 12.3777546833%; Total net sales retained. |
| NVIDIA revenue growth, deterministic | CORRECT_ANSWER | CORRECT_ANSWER | 114.2034076360%; Revenue retained. |
| Tesla revenue growth, deterministic | CORRECT_ANSWER | CORRECT_ANSWER | -2.9306991504%; Total revenues retained. |

**Totals: 7 correct answers, 1 unexpected abstention, 1 operational error, 0 incorrect emitted answers.** Both remaining failures are explicitly recorded, not counted as successful safeguards. This selected nine-case replay is not a general accuracy estimate, and the full 96-case matrix was not rerun.

## Remaining failures

For Walmart revenue growth, the policy restricted revenue proposals to the two reported Total revenues rows. The Verifier rejected both with contradictory reasoning about consolidated operations versus operations. The Corrector returned NO_VALID_EVIDENCE; the run ended INSUFFICIENT_EVIDENCE despite an answerable source. The revenue-definition substitution is prevented, but the agent-enabled task is not fixed end to end.

For Walmart operating-margin change, the Verifier falsely rejected the correct operating-income row and a later review failed with `VerifierContractError: A consolidated-scope PASS must cite the actual consolidated statement heading/context`. This is a Verifier/recovery failure, not an incorrect revenue calculation.

The Microsoft numeric/date parser defects were outside this change and were not retested here. Scope-verification and citation-contract handling also remain unchanged.

## Validation

- Focused tests: **39 passed**, including 18 new revenue-basis cases covering both runtime modes, net-sales-only filings, partial totals, conflicting/duplicate totals, structurally invalid alternatives and stale proposals.
- Full automated suite: **153 passed, 3 skipped**. The skipped cases are optional live encoder checks and a Windows-only check.
- `git diff --check` passed.
- All 9 replay case records, 9 unique readable audits, source hashes and recomputed grades reconciled. The original baseline still contains 96 cases.
- Saved replay code identity matches the current source identity. Expected references remain on the evaluation side, outside runtime requests.

## Review files

- [Batch report](../artifacts/multi-company/revenue-basis-2026-11-12/report.md)
- [Before/after comparison and validation](../artifacts/multi-company/revenue-basis-2026-11-12/validation.json)
- [Per-request CSV](../artifacts/multi-company/revenue-basis-2026-11-12/summary.csv)
- [Append-only journal](../artifacts/multi-company/revenue-basis-2026-11-12/cases.jsonl)
- [Frozen case definitions](../artifacts/multi-company/revenue-basis-2026-11-12/cases.snapshot.json)
- [Replay identity](../artifacts/multi-company/revenue-basis-2026-11-12/manifest.json)
- [Original stress-test report](MULTI_COMPANY_STRESS_TEST_RESULTS.md)

Changed implementation: `config/financial_concepts.py`, `tools/concept_validation.py`, `services/pipeline.py`. New tests: `tests/test_revenue_basis.py`. Documentation: `README.md`, `reports/CURRENT_SYSTEM_STRUCTURE.md`, and this report.
