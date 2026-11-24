# Current-assets recovery and six-company replay

The Apple and Tesla recovery controls deliberately promote **Total assets** to answer a current-ratio question. The required numerator is **Total current assets**. In the previous [scope replay](SCOPE_VERIFIER_FIX_RESULTS.md), the Verifier questioned the promoted row, then the Corrector declined four candidate groups per company even though each candidate pool contained the correct row.

## Change under test

The correction node assesses the concept and issuer scope of alternatives inside the permitted search scope. A replacement qualifies for the new Python path when its facts for every requested period carry a registered US-GAAP concept, meet the existing structural checks, have established issuer scope, and resolve to one distinct XBRL fact identity across the candidate rows. Exact repeated copies count once. Python proposes the existing evidence ID. The normal verification and acceptance guard still determine whether it reaches the calculator.

For current-assets recovery, a row whose US-GAAP tags all differ from AssetsCurrent and whose label also differs from the registered current-assets labels is excluded with its ID and actual tags in the audit. For a custom or untagged line item, a same-filing liability group heading and an explicitly liability-related row label can establish the mismatch together. The exclusion records both source texts and the group locator. A generic debt-securities label does not trigger this rule. Other unresolved custom and untagged rows remain eligible for model review. When alternatives need model judgment, the Corrector receives each candidate's own facts, label, concept and scope assessments. Its response schema requires an assessment category and a source detail for every supplied ID.

## Evaluation design

Both positive controls keep the reviewed numerator available. Both negative controls withhold current-assets rows from the ranked candidate pool on every retrieval and expansion while keeping the original filing and other balance-sheet rows. A negative control passes only if the wrong row was promoted, at least one replacement was withheld, recovery ran, the system accepted no current-assets row, and it emitted no calculation. The controls test recovery after a deliberately poor first choice.

The full replay uses the 96 original request definitions in the original order, including the two positive controls. The two negative controls are additional. Input files, source hashes, and original reference fields match the frozen pilot. Version-2 scoring also checks independently reviewed financial fact identities and preserves the strict-label comparison. The same six companies and repeated requests make this a regression test on known filings.

A first four-case run produced the expected financial outcomes, but inspection showed the model repeated three labels as its reasons on the Tesla negative control. A second four-case run produced the expected financial outcomes, but the model categorized three balance-sheet liabilities as a statement mismatch. A third control run correctly abstained but labeled the declined candidates as supported. A subsequent live probe required action-specific JSON shapes. It ended in an operational error when the local decoder twice generated incomplete JSON. That attempt remains recorded. The final implementation uses one compact model response shape, restricts reason categories for each candidate, and validates the consistency of the chosen action in Python. A decline cannot mark a candidate as supported. Statement, unit and period have already passed. A model can cite an unresolved concept or scope only when that check remains open. All three preliminary four-case runs and the two interrupted preliminary matrix runs are retained separately. Only the final frozen-code runs count below.

## Final recovery controls

| Company | Current-assets replacement available | Outcome | Current-ratio change | Model calls | Seconds |
|---|---|---|---:|---|---:|
| AAPL | Yes | CORRECT_ANSWER | +0.0259803457 | verifier 1 | 23.93 |
| AAPL | No | CORRECT_ABSTENTION | — | verifier 1 | 18.78 |
| TSLA | Yes | CORRECT_ANSWER | +0.1394944963 | verifier 1 | 21.75 |
| TSLA | No | CORRECT_ABSTENTION | — | verifier 1 | 26.34 |

Both correct replacements received a new PASS and passed the final guard. The prior two positive runs used eight Corrector model calls in total. The revised correction node proposed both replacements directly from XBRL evidence, using zero Corrector model calls. Each control still made one Verifier model call for the deliberately promoted initial row. Timings describe individual runs.

In the Tesla negative control, the audit identifies three custom-tagged liability rows by label and the same-filing group heading Current liabilities at table 21, row 21. Removing the valid current-assets facts prevents a calculation even though other numeric rows remain available.

[Per-case results, including the four recovery controls](CORRECTOR_RECOVERY_CASES.csv)

## Full replay

| Group | Requests | Correct financial answers | Correct abstentions | Incorrect answers | Unexpected abstentions | Operational errors |
|---|---:|---:|---:|---:|---:|---:|
| First pass | 56 | 44 | 12 | 0 | 0 | 0 |
| Repeats | 40 | 30 | 10 | 0 | 0 | 0 |
| Total | 96 | 74 | 22 | 0 | 0 | 0 |

All 96 final grades were recomputed from case snapshots and reconciled with their audits. Each positive control selected the independently reviewed fact, and the verifier, guard and calculator used the same evidence ID. Each negative control withheld every independently equivalent numerator row. The matrix generated six Planner calls and two Verifier calls with local `qwen2.5:3b`. The graph's correction node handled both recovery cases without a Corrector model call.

The four Microsoft display-label differences remain visible under strict-label comparison. The selected XBRL fact identities and calculations match the independent references. The broad comparison against the [original pilot](MULTI_COMPANY_STRESS_TEST_RESULTS.md) includes the intervening revenue, parser, verifier and scoring revisions. The two matched recovery controls provide the direct comparison for this correction change.

[Download the per-request results](CORRECTOR_RECOVERY_CASES.csv). Filter the batch column to `full-replay` for the 96-request matrix.

The automated suite passed **267 tests**, with three optional or platform-specific skips. Regression tests include identical repeated facts, conflicting identities, missing tags, restricted scope, custom tags, liability group evidence and decision/reason consistency. The live tests used the same Python backend as Streamlit and saved one audit per request.

## Remaining model limitation

**FAILED isolated model probe.** After the full replay, the final Corrector received the exact archived input containing three Tesla liability rows, deliberately bypassing the new candidate filter. On both attempts Qwen began selecting a debt row as current assets and generated an incomplete JSON response at the configured output budget. The decoder returned an operational error. No response passed validation. This isolated call is outside the 96 end-to-end requests and four controls. In the normal program these three particular rows are excluded using their source group and labels.

The live controls verify recovery from a uniquely supported fact and abstention when that fact is withheld. The final four controls exercised zero generative Corrector calls. Reliability on truly ambiguous companies or concepts that reach the model remains open. A useful next experiment is a held-out set of ambiguous, eligible alternatives with independently reviewed expected decisions and diagnostics, before making further model or prompt changes.

The local replay stores the raw probe responses in `artifacts/multi-company/corrector-2026-11-24/archived-corrector-probe.json`.

## Reproduction with the retained corpus

Use a fresh output directory under `artifacts/multi-company`. From the repository root, the following commands reconstruct the 96 requests and the four separate recovery controls.

```bash
replay_dir=artifacts/multi-company/corrector-reproduction
.venv/bin/python -m evaluation.cases --references evaluation/cases/scope_references_v2.json --output "$replay_dir/matrix.json"
.venv/bin/python - "$replay_dir" <<'PY'
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
snapshot = json.loads((root / "matrix.json").read_text())
positives = [c for c in snapshot["cases"] if c["group"] == "recovery"]
negatives = [
    dict(c, case_id=c["ticker"] + "-withheld-replacement",
         fault="withhold_current_assets", expected_status="INSUFFICIENT_EVIDENCE")
    for c in positives
]
snapshot["cases"] = sorted(positives + negatives, key=lambda c: c["case_id"] != "TSLA-withheld-replacement")
(root / "recovery-controls.json").write_text(json.dumps(snapshot, indent=2))
PY
HF_HUB_OFFLINE=1 .venv/bin/python -m evaluation.batch_runner --cases "$replay_dir/recovery-controls.json" --output "$replay_dir/controls"
HF_HUB_OFFLINE=1 .venv/bin/python -m evaluation.batch_runner --cases "$replay_dir/matrix.json" --output "$replay_dir/full"
```
