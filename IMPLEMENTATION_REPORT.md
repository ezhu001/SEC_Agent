# Financial filing agent implementation report

The repository now contains a runnable Streamlit application, CLI, typed contracts, three model-driven roles, structured filing/XBRL tools, batched cached FinBERT retrieval, explicit LangGraph orchestration, deterministic evidence acceptance/calculation and per-request audit artifacts. The [README](README.md) contains the final tree, responsibilities, graph diagram, setup/Ollama/GPU instructions, launch/test commands, CLI examples and limitations.

## Verified demonstrations

These are real local Qwen and FinBERT runs against the retained Apple development HTML. The recovery scenario uses an explicitly controlled two-row candidate pool and the notebook's original revenue query; it is a development demonstration, not a held-out result.

| Scenario | Observed behavior | Final outcome |
|---|---|---|
| Normal success | Hybrid retrieval proposes Total net sales; Qwen PASS; guard passes; Python computes growth | `SUCCESS`, 6.425511782832739 percent |
| Selection error and recovery | FinBERT proposes Total cost of sales; Qwen FAIL; corrector selects existing Total net sales ID; second verification PASS; guard passes | `SUCCESS`, same deterministic growth; one correction round and one expanded search |
| Missing periods | Request asks for FY2019/FY2020 values absent from the parsed Apple development evidence; broader search still cannot supply requested periods | `INSUFFICIENT_EVIDENCE`; no verifier acceptance and no calculation |

Audits retained in this workspace:

- Normal: `artifacts/live-demo/runs/98d4266c7a8d44a08cc1420a101fdeff/audit.json`.
- Recovery: `artifacts/live-demo/runs/ee709cf313954f5da7205eb1457ca542/audit.json`.
- Missing periods: `artifacts/live-demo/runs/135102fb859540b3844508399cf2d182/audit.json`.
- Consolidated outcomes: `artifacts/live-demo/verified-summary.json`.

Earlier failed attempts remain in the audit directories. One live planner attempt returned invalid bare-year tokens and query keys and stopped with `ERROR`. An initial recovery attempt overlooked the valid later candidate and safely abstained. Generic schema feedback, explicit context limits, compact evidence payloads and instructions to compare every candidate were strengthened; the subsequent recovery run succeeded. These prompts have been developed here and must be frozen before held-out evaluation. The live verifier also called the cost-of-sales mismatch `wrong_statement`; its rejection was useful, but its error taxonomy label was imprecise. No rule forced the live model to choose the correct ID.

## Validation

- Complete suite with live encoder tests enabled: **49 passed**. It includes the Streamlit form/answer test, original notebook pooling/cosine parity, CPU inference and CUDA inference. The machine's CUDA hardware was available, so the CUDA test ran rather than skipping.
- Separate clean `.venv-check`, built from `requirements-lock.txt` and an editable package install: **45 passed** for application/source tests, including fresh-process CLI and demonstration subprocesses. No notebook process or variables were used.
- Both installed environments passed dependency compatibility checks.
- Streamlit was started on `http://127.0.0.1:8501`; `/_stcore/health` returned `ok`.
- An offline scripted run also demonstrated success, recovery with re-verification and abstention. These scripted runs are explicitly labeled and do not represent live model accuracy.
- Final test report: `artifacts/final-tests.xml`. Bytecode compilation checks cover application, evaluation and helper scripts.

The Windows sandbox prevents Streamlit's test runner from creating its asyncio socket pair; a timed stack dump identified the blocked `socket.accept`. UI and complete-suite verification were run with normal local socket access and passed. A setuptools editable build under the sandbox's brace-containing profile path also failed; installing the same clean environment with normal permissions succeeded. Neither required weakening application evidence checks.

## Runtime and acceleration

Tested interpreter: Python 3.11.13. The CPU lockfile records the initial CPU environment; the active `.venv` uses PyTorch 2.7.1+cu128 after the documented official CUDA-wheel replacement. FinBERT CUDA was verified on NVIDIA GeForce RTX 4060 Laptop GPU, and the CPU implementation was verified separately. Transformers was 4.57.6; LangGraph 1.2.19; Streamlit 1.66.1.

Encoder revision: `88ab954a39ea6d3ce2b62cff086dd5ad1172c664`.

Observed Qwen digest: `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` (`qwen2.5:latest`). Ollama's diagnostics reported `size_vram: 0` for the resident decoder during the final status probe. Therefore decoder GPU execution was **not** demonstrated. The application leaves decoder serving/allocation to Ollama and reports the diagnostic honestly; CPU Qwen remains functional. This serving configuration may need separate Ollama GPU troubleshooting on this machine. The app does not claim that a GPU-visible PyTorch environment implies GPU-enabled Ollama.

## Preserved notebook behavior

- The `yiyanghkust/finbert-pretrain` tokenizer/encoder, 256-token default, attention-mask mean pooling, L2 normalization and cosine similarity. The real regression check reproduced scores about **0.5112578 for total net sales** and **0.5349339 for total cost of sales**, preserving the original ranking failure. Batching/inference mode changes execution efficiency rather than representation semantics.
- Separate Qwen verification and correction roles, temperature zero, supplied-evidence-only decisions and supplied-ID membership checks. The verifier does not choose replacements or compute the authoritative answer.
- Deterministic revenue growth, operating-margin change and current-ratio change formulas and their Apple results. Seven further registered formulas extend the application without model-generated arithmetic.
- Mechanical evidence checks remain distinct from model semantic verification.
- Saved research observations and key original function/prompt sources are frozen in `evaluation/fixtures/notebook_snapshot.json`, outside production state. The retained Apple HTML, original metric definitions in the snapshot, and external references remain development material.
- Caveats: one filing/three original tasks, conditional candidate recall, exploratory safeguard development, stronger information in exact-alias benchmarks, correlated errors across repeated model roles, and no general robustness claim.

## Intentional changes and reasons

| Change | Engineering reason |
|---|---|
| Explicit LangGraph nodes, conditional destinations and typed serializable state | Replace notebook execution order and global DataFrame/model/task coupling. |
| Model-driven planner plus deterministic formula allowlist | Accept user questions without permitting unrestricted formulas or guessed periods. |
| Gold-free production retrieval with separately exposed hybrid signals | Notebook stress generation always inserts gold evidence and cannot test absence. |
| Sufficiency and terminal abstention | A top-ranked candidate does not establish that requested evidence exists. |
| No restoration of rejected baseline; corrected rows are reverified | The notebook could retain failed evidence and did not reverify replacements. |
| Guards and final input checks block arithmetic | Notebook guard output was recorded but did not control calculation. |
| Header/context-aware facts with normalized scale and explicit periods | Fixed FY2025/FY2024 positions, number filtering below 100 and deduplication of equal financial values were development-specific. |
| DOM table/cell provenance with source hash | XBRL/HTML structural parsing uses a different table inventory than pandas; IDs cannot exactly match notebook table IDs. |
| Strict JSON schemas, validation feedback and bounded context/chunks | Permissive defaults/greedy JSON extraction could conceal malformed or invalid decisions; large prompts can lose relevant context. |
| Lazy process-cached encoder and persistent row embeddings | Avoid repeated candidate encoding and import-time model/network side effects. |
| Unique audit directories and actual revisions/digests | Fixed filenames overwrite runs; mutable model tags cannot establish repeatability. |

The exact-alias benchmark and FinBERT dual-view reranker are retained in the research snapshot rather than installed as extra production agents. Their historical outputs remain available, but this implementation does not provide full executable reproductions of those two benchmark runners. That scope distinction is intentional: the default application uses the requested heterogeneous Qwen verification/recovery graph. A general held-out evaluation suite remains future research.

## Remaining practical limits

Live SEC lookup/download was not exercised against SEC during validation because no new requester identity was configured; local acquisition and mocked ticker/accession/cache/retry paths were tested. Configure your own identifiable SEC contact before network use. Other companies/layouts, uncommon XBRL transformations, duplicate/restated facts, ambiguous fiscal labels and dimensional reporting remain sources of abstention or error requiring held-out evaluation. Plain HTML evidence depends on explicit header/unit context. Recovery is bounded and not an exhaustive filing search.

The production concept map and hybrid weights are transparent engineering defaults, not calibrated thresholds. The model may still falsely pass a wrong concept; mechanical guards cannot eliminate semantic errors. Qwen roles share a model. No benchmark result here establishes general safeguard effectiveness. These limits are surfaced in the README rather than hidden behind the successful development examples.

## Research record preservation

The original notebook at `C:/Users/13466/fall2026/VIP2026/M4_InitialResults_multiagent1py1.ipynb` was neither overwritten nor deleted. Its SHA-256 before and after implementation is:

`d44419f05b5baf1aa3565bc0ec7476f5a659a34ea5d9e2d2443b507b0919fe94`.

The overview document was read only. No application code depends on either document or on a notebook kernel at runtime.
