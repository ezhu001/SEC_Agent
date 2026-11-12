# Source scope, Verifier contract v2 and fact-equivalence scoring

Completed November 12, 2026. **All five changes are implemented. The final targeted replay has zero Verifier contract errors; two deliberately faulted recovery cases still fail because the Corrector rejects available valid replacements.** Those failures remain explicitly recorded.

## Implemented behavior

1. **Preserved source evidence.** Evidence rows retain statement headings, row-group headings, issuer identifiers/schemes, XBRL context IDs, dimensions and consolidation declarations, with source locations and filing hashes. Heading extraction preserves DOM text when a word spans adjacent inline elements, including Microsoft's `INC` + `OME STATEMENTS`. A neighbouring financial table cannot inherit a primary statement's heading through another table.
2. **Source-backed scope assessment.** `ESTABLISHED`, `RESTRICTED` and `UNRESOLVED` are separate results. A primary statement needs issuer-matching contexts and either an explicit consolidated heading or an issuer-associated consolidation declaration. Plain HTML requires an associated declaration and explicit consolidated heading. Repeated note totals can inherit established scope only through exact same-filing XBRL fact identities. Empty dimensions alone are insufficient. Segment/subsidiary/parent-company groups and contradictory issuer identities cannot be overridden by a global consolidation declaration.
3. **Source-ID Verifier output.** The agent returns check/status/evidence IDs/reason code. The dynamic JSON grammar restricts IDs separately for each open check. Python independently validates filing/row binding and evidence type, resolves the original source excerpts, and aggregates the overall verdict. The model does not copy quotations or invent a consolidated heading. Resolved Python checks cannot be reopened.
4. **Explicit uncertainty and bounded recovery.** Unsupported evidence produces valid UNCERTAIN rather than unsupported PASS. Persistent malformed/invalid reviews remain operational errors after one contract-repair attempt. Valid FAIL/UNCERTAIN reviews can enter bounded recovery; an unchanged uncertain selection is excluded, while changed supporting evidence can permit another review. Explicitly rejected selections stay excluded. All-resolved reviews bypass the Verifier model and record the source-backed decision.
5. **Independent evaluation-side equivalence.** Version-2 scoring requires reviewed same-filing fact identity, including concept, context/entity, monetary unit/scale, fiscal dates, dimensions and normalized values. It records label agreement separately and retains a version-1 strict-label comparison. References are extracted from the previously reviewed primary source rows by a separate evaluation utility, not by the application's parser or scope assessor. Reference identities and scoring settings never enter runtime requests.

Versions: parser **ixbrl-table-v9**, prompt **4**, review contract **2**, explicitly opted-in scoring **2**. Historical cases retain scoring version 1 by default. No LangGraph nodes were added; the existing 14-node topology and Python calculator remain.

## Tests and source checks

- **243 automated tests passed; 3 skipped.** Skips are the existing optional live encoder and Windows-only checks.
- Negative cases cover restricted dimensions, foreign issuers/files/headings, parent-company and subsidiary groups, empty dimensions without proof, unequal facts, different contexts/periods/concepts, invalid IDs, wrong evidence types, unsupported scope decisions and stale uncertainty records.
- The reference-builder tests reject changed raw amounts, issuer identities and currencies. Scoring rejects Walmart Net sales as a substitute for its reviewed Total revenues.
- All **24 reviewed primary component rows** across AAPL, TSLA, MSFT, AMZN, WMT and NVDA have established scope. All **48 reviewed fact identities** match the independent references. Source hashes remain unchanged.
- Old parser caches are invalidated. The original HTML is retained without edits.
- `git diff --check` passed.

## First replay and refinement

The first 20-case attempt recorded **16 correct answers, 2 correct abstentions and 2 operational errors**. Its two controlled cases reached genuine unresolved-concept reviews, but Qwen cited IDs of the wrong evidence type. The first schema constrained IDs to the overall catalogue; Python correctly rejected those references.

The refinement constrains the allowed ID list **inside each check's grammar** and removes irrelevant evidence from the model catalogue. The Python validator remains as a backstop. The initial failed records are retained in [the first attempt](../artifacts/multi-company/scope-fix-2026-11-12/validation.json).

## Final replay: identical 20-case snapshot

The second attempt used the identical case snapshot, unchanged source/reference amounts and the same configured local model. Code identity was fixed during each attempt. Real FinBERT and local Qwen were used; deterministic source decisions are identified separately from model calls.

| Group | Cases | Final outcome |
|---|---:|---|
| Microsoft explicit metrics, both modes | 6 | 6 CORRECT_ANSWER |
| Microsoft missing-year controls, both modes | 2 | 2 CORRECT_ABSTENTION, no model calls |
| Microsoft free-text planner request | 1 | CORRECT_ANSWER |
| Earlier Apple ratio and Walmart revenue/margin/ratio failures | 4 | 4 CORRECT_ANSWER |
| Deliberately promoted Total assets, Apple and Tesla | 2 | **2 UNEXPECTED_ABSTENTION — FAILED** |
| Tesla, NVIDIA and Amazon ratio regressions | 3 | 3 CORRECT_ANSWER |
| Apple revenue and operating-margin regressions | 2 | 2 CORRECT_ANSWER |

**Final totals: 16 correct answers, 2 correct abstentions, 2 unexpected abstentions, 0 operational errors, 0 incorrect emitted financial answers.** The two unexpected abstentions are answerable tasks and are not counted as successful safeguards.

## Which agents actually ran

Generation calls: **Planner 1, Verifier 2, Corrector 8**. The two live Verifier reviews both passed the new contract. Most natural evidence selections had all required checks established by Python and did not call the Verifier model. The audit records 23 `deterministic_source_scope`, 5 `deterministic_concept_rules` and 2 `qwen` review records across the batch.

These results demonstrate changes to the program's evidence and routing behavior. They do not show that Qwen became a more accurate scope reviewer, and timings are not a controlled performance comparison.

## Remaining Corrector failures

Both controlled cases promoted Total assets instead of current assets. The Verifier produced an accepted UNCERTAIN review and recovery ran. In each case, the Corrector generated four chunk reviews returning NO_VALID_EVIDENCE. Independent inspection of the actual supplied candidates confirmed that the reviewed correct Total current assets fact was present.

The requests therefore ended INSUFFICIENT_EVIDENCE despite answerable sources. Recovery was exercised, but it did not succeed. This is now a Corrector candidate-selection failure, rather than a rejected Verifier citation. No substitute number was restored and no derived answer was emitted.

These failures remain in the journal, per-case snapshots, report and validation file. Further work should address the Corrector's use of candidate concept/scope evidence; this change does not claim that issue is solved.

## Microsoft display-label comparisons

Four successful cases—revenue growth and operating-margin change in both modes—still have a version-1 strict-label grade of WRONG_ANSWER. Their selected note row says Revenue; the primary statement says Total revenue. Their XBRL fact identities match the independently reviewed primary facts exactly.

Version 2 records financial correctness and `label_match=false, fact_equivalent=true` separately. This changes the evaluation policy, not the underlying numbers. The historical raw grades have not been overwritten. Walmart's genuinely different net-sales basis remains rejected by the independent equivalence tests.

## Reconciliation and limits

All 20 final case records, 20 unique readable audits, grades, source hashes, accepted verified IDs and source-scope proofs reconciled. Runtime model requests were checked for evaluation reference fields. The final source identity matched its frozen manifest. The original batches remain retained: baseline 96, revenue-policy replay 9, parser replay 12, first scope attempt 20.

This is a selected regression batch across known pilot sources, not a held-out accuracy estimate. The full 96-case matrix was not rerun. Unusual/custom source layouts and unresolved semantic evidence can still abstain or require model review. No new browser GUI observations are claimed.

## Records

- [Final validation, role counts, label comparisons and remaining failures](../artifacts/multi-company/scope-fix-2026-11-12-r2/validation.json)
- [Final per-case report](../artifacts/multi-company/scope-fix-2026-11-12-r2/report.md)
- [Final CSV](../artifacts/multi-company/scope-fix-2026-11-12-r2/summary.csv)
- [Append-only journal](../artifacts/multi-company/scope-fix-2026-11-12-r2/cases.jsonl)
- [24-row/48-fact source checks](../artifacts/multi-company/scope-fix-2026-11-12-r2/source-validation.json)
- [Frozen case snapshot](../artifacts/multi-company/scope-fix-2026-11-12-r2/cases.snapshot.json)
- [Final code/model identity](../artifacts/multi-company/scope-fix-2026-11-12-r2/manifest.json)
- [First attempt and its failures](../artifacts/multi-company/scope-fix-2026-11-12/report.md)

## Changed files for this work

- Runtime schemas: `schemas/evidence.py`, `schemas/results.py`.
- Source extraction and assessment: `tools/filing_parser.py`, `tools/xbrl.py`, new `tools/scope_validation.py`.
- Review and routing: `agents/verification_contract.py`, `agents/verifier.py`, `services/pipeline.py`, `config/prompts.py`, `config/settings.py`.
- Evaluation: `evaluation/cases.py`, `evaluation/batch_runner.py`, new `evaluation/review_fact_identities.py`, new `evaluation/cases/scope_references_v2.json`, `evaluation/doubles.py`, `evaluation/review_double.py`.
- Tests: new `test_scope_validation.py`, new `test_fact_equivalence.py`, and updates to `test_verifier_contract.py`, `test_metric_workflow.py`, `test_qwen_modes.py`, `test_revenue_basis.py`, `test_early_eligibility.py`, `test_converted_filing.py`, `test_parser_formats.py`.
- Documentation: `README.md`, `QWEN_VERIFIER_CONTRACT.md`, `evaluation/README.md`, `reports/CURRENT_SYSTEM_STRUCTURE.md`, and this report.
