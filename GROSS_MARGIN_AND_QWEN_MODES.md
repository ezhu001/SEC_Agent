# Gross profit dimension correction and optional Qwen roles

The supplied failed run `c07bdbccda3f4d6db34fd628d53022f4` proposed the correct reported row, `Gross margin`, with monetary values for FY2025/FY2024. Qwen incorrectly treated the name as necessarily denoting a percentage and rejected it as a gross-profit source. The runtime alias registry already allowed the name, but the decoder payload did not include that concept definition or independent accounting reconciliation.

The correction is shared, unit-aware concept interpretation rather than an Apple-specific expected-answer rule. A reported monetary Gross margin subtotal may supply canonical `gross_profit`; a percentage/ratio row cannot. The decoder receives canonical meaning, accepted reported labels, expected dimension and relevant taxonomy concepts. Inventory and hybrid concept signals use the same dimension constraint.

Python now checks the reported monetary subtotal against unique, compatible same-table revenue and cost-of-sales rows. The certificate records all evidence IDs and exact period-level equality checks. If that identity passes, the concept is validated directly without asking Qwen to reinterpret the label or perform the arithmetic. A mismatch cannot be approved by a decoder. An unavailable identity is not fabricated; other configured concept checks/model review apply. Rejected unchanged evidence IDs are excluded from subsequent proposals/recovery.

## Qwen setting

- Sidebar: **Enable Qwen agents**.
- Environment: `FFA_QWEN_ENABLED=false`.
- CLI: `--no-qwen`.

OFF disables all decoder planning, verification and recovery requests, including the optional CLI status probe. Choose a registered metric and explicit fiscal years. Free-text planning in this mode requests menu input. FinBERT retrieval remains active. Deterministic registered-concept, statement, source, period, unit and completeness checks still apply; ambiguity or missing data still causes abstention. OFF does not mean unconditional acceptance of FinBERT top-1.

ON permits Qwen where model interpretation is needed. Strong independently reconciled source identities take precedence and do not need an additional model call. Each verification record names its method (`deterministic_accounting_identity`, `deterministic_concept_rules` or `qwen`), and the final UI/audit shows the run's configured mode and decoder-call count. Deterministic records do not invent a probability/confidence score.

## Actual local-model results

Both modes ran against the supplied converted Apple filing with real FinBERT retrieval:

| Result | Value |
|---|---:|
| FY2024 gross profit amount, millions | 180,683 |
| FY2025 gross profit amount, millions | 195,201 |
| FY2024 gross margin rate | 46.206349815233935% |
| FY2025 gross margin rate | 46.90516410716045% |
| Change | +0.6988142919265172 percentage points |

Qwen OFF: `SUCCESS`, 0 decoder calls, audit `artifacts/runs/69874559c69042078b898023f9add070/audit.json`.

Qwen ON: `SUCCESS`, 1 decoder call for revenue review, audit `artifacts/runs/7dd50cdc8aff4b46a3b5cecb34d1014a/audit.json`. The gross-profit component used the Python accounting identity, avoiding the original false rejection. Both modes used the same Python calculator and comparison tool. Summary: `artifacts/gross-margin-mode-summary.json`.

Full regression: **79 passed, 1 unavailable-CUDA skip**, including the actual UI toggle, zero-call OFF mode, missing-period preservation, percentage-row rejection, reconciliation mismatch, and a test decoder reproducing the original label misconception. Report: `artifacts/gross-qwen-final.xml`.

The original notebook, user filing and failed audit were not overwritten. Rule-only mode is limited to registered, unambiguous source concepts; it is not a claim of general semantic understanding or calibrated financial accuracy.
