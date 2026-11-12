# Parser fix and Microsoft replay

Completed November 12, 2026. **The Microsoft numeric crash and incorrect filing-date metadata are fixed. All nine replayed Microsoft requests completed evidence construction.** Agent verification failures and two frozen-label scoring flags remain separately recorded.

## Cause and implementation

Microsoft's retained HTML displays a negative amount across adjacent cells: `(4,901` and `)`. The previous numeric pattern allowed either parenthesis independently, then attempted `float('(4901')`. The exception occurred while constructing retrieval text and aborted evidence construction, including requests for unrelated metrics.

The same source reports its period end as `June 30,2025`. The previous flexible date parser failed to preserve that explicit year and returned June 30, 2026. This metadata is used in fiscal-period mapping, so fixing only the crash would leave a separate date defect.

Changes:

- `tools/numeric_parser.py`: incomplete numeric fragments return `None`; complete parenthesized negatives retain their sign, including whitespace/line breaks. Nonfinite numeric results are rejected.
- `tools/filing_parser.py`: plain-HTML display fragments may be joined only within one row and one explicitly mapped fiscal-year column group containing one numeric payload. Unsupported joins across years/rows, incomplete groups and ambiguous multi-payload reconstructions remain unresolved. Complete duplicate amounts remain separate facts for downstream ambiguity checks. Original cells and the numeric cell position remain preserved. Date headers also support a comma immediately followed by the year.
- `tools/filing_loader.py`: explicit complete ISO or English month/day/four-digit-year dates are parsed without filling a year from today. Dates are reparsed from cached source HTML, correcting old cached metadata.
- `config/settings.py`: parser version increased from `ixbrl-table-v5` to `ixbrl-table-v6`, invalidating old evidence/embedding caches.

Inline XBRL sign, scale and context handling remains authoritative. No source HTML was edited, no amounts were synthesized, and the source files were not downloaded again. Broader Verifier and scoring-policy changes were outside this fix.

## Source and automated checks

- **55 focused tests passed** for parser formats, sources and converted HTML.
- **196 automated tests passed; 3 skipped** in the full suite. Optional live encoder and Windows-only checks were skipped.
- The new `tests/test_parser_formats.py` supplies 43 regression cases covering incomplete fragments, nested tags/line breaks, split parentheses, currency formatting, fiscal-year boundaries, duplicate amounts, explicit dates, inline signs/scales, stale source metadata and evidence-cache invalidation.
- All six retained pilot filings parsed successfully from source. All **48 independently reviewed primary component amounts and fiscal end dates** matched the frozen references. All six source hashes and filing period ends matched the corpus manifest.
- Microsoft produced **106 evidence rows** and the correct `period_end: 2025-06-30`. Its reported nonoperating amounts remained **-4,901 million for FY2025** and **-1,646 million for FY2024**, with their correct fiscal labels.
- `git diff --check` passed.

## Live replay: 12 requests

The existing runner used unchanged pilot case definitions and references, real FinBERT and the configured local Qwen service. Application code stayed unchanged during the replay. All nine Microsoft cases had previously stopped at the parser; this replay also included three existing regression cases. The full 96-request matrix was not rerun.

| Request | Frozen scorer grade | Result |
|---|---|---|
| MSFT revenue growth, deterministic | **WRONG_ANSWER — LABEL FLAG RETAINED** | 14.9321562324%; numeric inputs and result match. See equivalent-fact review below. |
| MSFT operating-margin change, deterministic | **WRONG_ANSWER — LABEL FLAG RETAINED** | 0.9776566676 percentage points; numeric inputs and result match. Same label issue. |
| MSFT current-ratio change, deterministic | CORRECT_ANSWER | 0.0784915413 ratio units. |
| MSFT revenue growth, agents | **OPERATIONAL_ERROR — FAILED** | Reached verification; consolidated-scope source-quote contract failed. |
| MSFT operating-margin change, agents | **OPERATIONAL_ERROR — FAILED** | Reached verification; same contract failure. |
| MSFT current-ratio change, agents | **OPERATIONAL_ERROR — FAILED** | Reached verification; same contract failure. |
| MSFT missing years, deterministic | CORRECT_ABSTENTION | No financial answer or model calls. |
| MSFT missing years, agents | CORRECT_ABSTENTION | No financial answer or model calls. |
| MSFT free-text planner request | **OPERATIONAL_ERROR — FAILED** | Passed planning and parsing; failed during scope verification. |
| WMT revenue growth, deterministic | CORRECT_ANSWER | 5.0700096432%; prior revenue-basis fix preserved. |
| AAPL revenue growth, deterministic | CORRECT_ANSWER | 6.4255117828%. |
| TSLA current-ratio change, deterministic | CORRECT_ANSWER | 0.1394944963 ratio units. |

**Raw totals: 4 CORRECT_ANSWER, 2 CORRECT_ABSTENTION, 2 WRONG_ANSWER, 4 OPERATIONAL_ERROR. Parser errors: zero.** The flags and failures have not been removed or counted as fully passing benchmark cases.

## Review of the two label flags

The frozen Microsoft reference accepts only `Total revenue`. Retrieval selected `Revenue` in table 71, row 38, under that source table's **Total** heading in the segment note. The primary statement uses `Total revenue` in table 23, row 11.

For both requested fiscal years, these rows repeat the **same XBRL concept and context IDs, values, currency, scale, start/end dates, instant/duration kind and empty dimensions**. The selected amounts are 281,724 million and 245,122 million. The frozen scorer reported only `Wrong source/label for revenue`; it reported no numeric, input, unit, date or dimension mismatch.

This source review identifies an equivalent repeated financial fact with a different display label. It differs from Walmart's earlier net-sales substitution, where the selected values and revenue basis were actually different. The raw `WRONG_ANSWER` grades remain retained; changing the scorer's label-equivalence allowance requires a separate reviewed change. These cases should not be described as newly observed arithmetic errors.

## Remaining limitations

All four agent-enabled answerable Microsoft requests still fail the Verifier's consolidated-scope quote contract. The parser fix allows those later failures to become visible; it does not resolve them. Ambiguous HTML fragments remain unavailable for arithmetic, and arbitrary cross-row visual reconstruction is not implemented.

The replay contains selected cases and no model repetitions. It is a regression check, not a general accuracy or speed estimate. The original 96-case baseline and the separate nine-case revenue-policy replay remain retained.

## Saved records

- [Replay report](../artifacts/multi-company/parser-fix-2026-11-12/report.md)
- [Validation, before/after cases and equivalent-fact review](../artifacts/multi-company/parser-fix-2026-11-12/validation.json)
- [Six-company source checks](../artifacts/multi-company/parser-fix-2026-11-12/source-validation.json)
- [Per-request CSV](../artifacts/multi-company/parser-fix-2026-11-12/summary.csv)
- [Append-only journal](../artifacts/multi-company/parser-fix-2026-11-12/cases.jsonl)
- [Frozen case definitions](../artifacts/multi-company/parser-fix-2026-11-12/cases.snapshot.json)
- [Code/model identity](../artifacts/multi-company/parser-fix-2026-11-12/manifest.json)

Changed files for this fix: `src/financial_filing_agent/tools/numeric_parser.py`, `tools/filing_parser.py`, `tools/filing_loader.py`, `config/settings.py`, new `tests/test_parser_formats.py`, the parser-version expectation in `tests/test_converted_filing.py`, `README.md`, `reports/CURRENT_SYSTEM_STRUCTURE.md`, and this report.
