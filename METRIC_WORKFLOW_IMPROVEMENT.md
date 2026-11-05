# Registered financial metrics and complete-input workflow

The reported Apple current-ratio failure was traced to a genuine period gap combined with incorrect routing. The converted FY2026 filing reports FY2026 and FY2025 balance sheets, but no FY2024 balance-sheet balances. Its income statement includes FY2024, which does not supply FY2024 current assets or current liabilities. The old parser also misclassified a cash-flow table as a balance sheet, and expanded retrieval could use an unrelated candidate's period availability to justify verifying an incomplete top row.

## Changes

- Added a metric menu backed by the deterministic formula registry. An explicit selection constructs the complete component/period plan without an LLM planner. Free-text planning remains available.
- Plans explicitly name `registered_python_calculator` and the `python_only` comparison policy. No agent-generated numerical result enters the calculator.
- Added an input-inventory graph node before retrieval. It lists every component/year cell and checks statement-period availability before model verification. Missing periods terminate with a specific explanation rather than sending incomplete evidence to Qwen.
- Improved primary statement identification, excluding cash-flow/shareholders-equity/comprehensive-income titles from balance-sheet evidence. Parser cache version is now `ixbrl-table-v5`.
- Retrieval requires unique requested-period facts. Sufficiency/proposal selection cannot borrow available periods from another row or another statement.
- Added optional supporting HTML uploads and explicit opt-in to searching cached same-company filings. The deterministic tool checks CIK when present in both filings, otherwise exact normalized entity name. It selects one complete filing; it does not splice incompatible facts across filings. Both the requested and selected source are audited, including unsuccessful searches. Primary evidence and supporting evidence artifacts are kept separately.
- The registered calculator is called only after all required components are verified and guarded. It computes each period's metric, absolute change, relative percentage change and direction in Python. If the previous metric equals zero, relative change is explicitly undefined while an otherwise valid absolute difference can still be returned.
- The UI displays the component/year inventory, inputs, period metrics and deterministic comparison, alongside live workflow progress and source-switch warnings.

## Current ratio change contract

Required cells are current assets and current liabilities for both the newer and older year. The arithmetic is fixed:

```text
current_ratio(year) = current_assets(year) / current_liabilities(year)
absolute_change = current_ratio(new) - current_ratio(old)
relative_change_percent = absolute_change / current_ratio(old) * 100
```

The final two quantities have different units: absolute change is in ratio units, while relative change is a percent. Neither is calculated or compared by Qwen.

## Verified results

Using the converted FY2026 file alone with requested FY2025/FY2024 now identifies two missing cells: FY2024 current assets and FY2024 current liabilities. It abstains before decoder verification or calculation.

Using the explicitly supplied same-company FY2025 filing to cover those missing years completed successfully with real local FinBERT and Qwen:

| Input or result | FY2024 | FY2025 |
|---|---:|---:|
| Current assets, millions | 152,987 | 147,957 |
| Current liabilities, millions | 176,392 | 165,631 |
| Current ratio | 0.8673125765340832 | 0.8932929222186667 |

Python-computed absolute change: **+0.025980345684583517 ratio units**. Relative change: **+2.9954997065077786%**. Audit: `artifacts/runs/629c1bdcadf84f22a356012c8322fcd9/audit.json`.

Full regression suite: **72 passed, 1 unavailable-CUDA skip**. New coverage includes verifying both components before a single calculation, four-cell inventory completeness, missing-period early abstention, explicit and cached supporting sources, wrong-company rejection, deterministic comparison and the Streamlit metric menu. Report: `artifacts/metric-final.xml`.

## UI usage

1. Choose **Current Ratio Change** from the metric menu.
2. Supply the filing and explicit periods, for example `FY2025 FY2024`.
3. If the primary file lacks one of those balance sheets, upload the older same-company filing under supporting filings, or enable the cached same-company search.
4. Run analysis and inspect the required-input matrix, verified source rows, both ratios and the deterministic comparison.

Ten existing registered formulas are exposed; the application does not claim to support every financial metric or reconstruct missing accounting facts. Unusual concept labels can still require model verification, and genuinely absent source facts still require another filing or a non-answer.
