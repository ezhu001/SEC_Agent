# Converted filing revenue calculation correction

The supplied failed run `d1f6416a0cda4b5e83e163461308fd1b` correctly retrieved Total net sales from operations table 22, row 6. Qwen returned PASS three times. Every mechanical guard failed only `known_units`: the numeric values and fiscal years were present, but `unit` and `currency` were null. Correction repeatedly returned the same unchanged row and exhausted its budget. The visible non-answer therefore arose from an overly restrictive parser/unit-validation path, not failure to locate revenue.

The supplied HTML is a converted EDGAR document. It retains date headers, dollar symbols and the statement heading “In millions,” but not usable Inline XBRL fact/context attributes. The original fallback required an explicit currency word near the table to recognize monetary values; it did not recognize the table's dollar symbols.

Changes:

- Recognize explicit table-level monetary evidence without treating every dollar sign as USD. Store a source-specific `unit_basis`; keep an unidentified ISO currency null.
- Permit currency cancellation only for registered dimensionless percent/ratio results when all unidentified-currency facts share one monetary table basis. Conflicting currencies, mixed identified/unidentified currencies, unrelated bases and genuinely absent units still fail. Dimensional monetary calculations require an identified currency.
- Recover entity/form metadata from an explicit converted filing title when DEI tags are absent.
- Advance parser cache version to `ixbrl-table-v4`, including the frozen configuration, so old null-unit artifacts are not reused. Preserve historical audits.
- Exclude unchanged deterministic guard failures from correction candidates. Surface the specific failed checks, rather than reporting only recovery exhaustion.
- Display the currency-cancellation explanation on successful UI results as well as non-answers.

The original attachments were not modified. A retained copy of the converted filing is now a regression fixture. Tests check FY2024/FY2025 explicitly even though this filing also includes FY2026, cold and warm caches, cross-source/mixed-currency rejection, absent units, metadata and the Streamlit result.

The real local Qwen/FinBERT pipeline was rerun with the exact user question and attached file. It returned `SUCCESS` with one verification PASS, zero corrections and:

| Fiscal year | Total net sales, in millions |
|---|---:|
| FY2024 | 391,035 |
| FY2025 | 416,161 |
| Increase | 25,126 |
| Percentage increase | 6.425511782832739% |

New audit: `artifacts/runs/1b1768087c0746e3bf0af27e789a2bc3/audit.json`.

Full regression/UI/encoder run: 55 passed, 1 CUDA test skipped because CUDA was not available in that test runtime. Report: `artifacts/revenue-fix-full.xml`. Subsequent focused tests also validate explicit dimensionless-only currency cancellation. The app on port 8501 was restarted and its health endpoint returned `ok`.
