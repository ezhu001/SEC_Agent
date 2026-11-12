# Financial filing evidence agent

An executable local application for answering bounded financial questions from SEC financial statement evidence. FinBERT retrieves rows; Qwen plans, verifies and corrects evidence; Python performs the authoritative calculations. LangGraph controls every transition. Unresolved evidence produces an explicit non-answer rather than an unsupported number.

The original research notebook was not modified. Its Apple development results are historical observations, not claims about this application's held-out performance. See [the architecture and migration plan](ARCHITECTURE_AND_MIGRATION_PLAN.md) and [the implementation report](IMPLEMENTATION_REPORT.md).

## Start the application

Run from this repository in PowerShell. Python 3.11 is the tested interpreter; the package declares Python 3.11–3.13 support. Install [uv](https://docs.astral.sh/uv/) if it is not already available.

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-lock.txt
uv pip install --python .venv/Scripts/python.exe -e .
Copy-Item .env.example .env
# Edit .env and supply your own identifiable SEC contact before network acquisition.
.venv/Scripts/python.exe -m streamlit run app.py
```

The default artifact root is `artifacts/`, with separate filing, parsed-evidence, embedding and per-run audit directories. A local HTML file does not require an SEC contact setting.

The lockfile records the tested Windows CPU dependency environment. The lockfile pins dependencies but is not a cryptographic supply-chain lock. No dependency downloads or model loads occur at module import.

### macOS (Apple Silicon)

From the repository root, use Python 3.11 and resolve the dependencies from `pyproject.toml` for macOS.

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest -q
```

FinBERT uses CPU with the default `auto` device setting on macOS. For an 8 GB Mac, set `FFA_DECODER_MODEL=qwen2.5:3b` in the repository's `.env` or export it in your shell. This selects the smaller Qwen model for local development. `config/research.json` continues to use its pinned research configuration.

Start `ollama serve` in a separate terminal if Ollama is stopped. Run `ollama pull qwen2.5:3b` if that model is absent from `ollama list`. FinBERT downloads its pinned weights on first use if they are absent from the Hugging Face cache. Set `HF_HUB_OFFLINE=1` when the weights are already cached and you want to use them offline.

```bash
.venv/bin/python -m financial_filing_agent.cli --status
.venv/bin/python -m financial_filing_agent.cli \
  --source evaluation/fixtures/apple_2025_10k.html \
  --question 'How did total net sales change from FY2024 to FY2025?'
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --browser.gatherUsageStats false
```

Open [Streamlit on localhost](http://127.0.0.1:8501). In the source field, enter `evaluation/fixtures/apple_2025_10k.html`. You can also switch off **Enable Qwen agents**, select **Revenue Growth**, and enter `FY2025 FY2024` to run the metric with deterministic evidence checks. For SEC network acquisition, set `FFA_SEC_USER_AGENT` in your environment before launching the app.

## Ollama setup

Install [Ollama](https://ollama.com/), start its local service, and pull the decoder:

```powershell
ollama pull qwen2.5:latest
# Use ollama serve only if the desktop service is not already running.
.venv/Scripts/python.exe -m financial_filing_agent.cli --status
```

The default endpoint is `http://localhost:11434`, the model is `qwen2.5:latest`, and temperature is zero. Each role uses separate instructions and a validated JSON schema through the [Ollama chat API](https://docs.ollama.com/api/chat). Invalid JSON, invalid schema, exhausted transport retries, missing local files and failed SEC requests produce `ERROR`; they are not classified as missing financial evidence.

The application records the actual model digest where the tags API is available. `config/research.json` additionally enforces the Qwen digest observed during implementation and pins the encoder revision, CPU device, prompts/settings and budgets. A different Qwen download must be recorded as a new research configuration, not silently substituted. `latest` plus temperature zero alone does not guarantee repeatability.

## GPU and CPU

FinBERT supports `FFA_FINBERT_DEVICE=auto`, `cuda` or `cpu`. Auto uses CUDA when the installed PyTorch build and driver expose it; otherwise it uses CPU. Explicit CUDA requests fail clearly if CUDA is unavailable. Both the encoder and token tensors use the selected device. Candidate encodings are batched under `torch.inference_mode()` and model instances are cached per process/configuration. The notebook's masked mean pooling, L2 normalization and cosine semantics are preserved.

This workspace was also validated with `torch==2.7.1+cu128` on the available RTX 4060. For this Windows/Python 3.11 setup, after installing the CPU lockfile, the tested CUDA replacement command is:

```powershell
uv pip install --python .venv/Scripts/python.exe 'torch==2.7.1+cu128' --index-url https://download.pytorch.org/whl/cu128
.venv/Scripts/python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

For different hardware/drivers, use the [official PyTorch installation selector](https://pytorch.org/get-started/locally/). Qwen remains hosted by Ollama; the application does not allocate its tensors. The status endpoint reports resident model VRAM when `/api/ps` exposes it. VRAM allocation is a diagnostic, not proof that every decoder operation ran on GPU. Parsing, lexical matching, routing, guards and arithmetic remain CPU tasks. GPU availability is not required for correctness.

## CLI and demonstrations

```powershell
# Local retained Apple development filing
.venv/Scripts/python.exe -m financial_filing_agent.cli --source evaluation/fixtures/apple_2025_10k.html --question 'How did total net sales change from FY2024 to FY2025?'

# Network acquisition (configure your SEC contact first)
.venv/Scripts/python.exe -m financial_filing_agent.cli --source AAPL --question 'What was operating margin in FY2025?'

# An explicit accession is preferable for repeatable source selection
.venv/Scripts/python.exe -m financial_filing_agent.cli --source AAPL/0000320193-25-000079 --question 'How did the current ratio change from FY2024 to FY2025?'

# Enforce frozen research settings; --full includes serializable state
.venv/Scripts/python.exe -m financial_filing_agent.cli --config config/research.json --source evaluation/fixtures/apple_2025_10k.html --question 'How did total net sales change from FY2024 to FY2025?' --full

# Fast deterministic control-flow demonstration using clearly labeled test doubles
.venv/Scripts/python.exe -m evaluation.runner

# Real Qwen and FinBERT: success, controlled ranking error/recovery, absent periods
.venv/Scripts/python.exe -m evaluation.live_demo --scenario all
```

Sources may be a local HTML/cache path, uploaded HTML in the UI, a direct SEC HTTPS document URL, ticker, CIK, accession or `ticker/accession`. Ticker/CIK without accession intentionally resolves the latest available 10-K and records that selection; freeze an accession for research. Bare accessions are resolved using their prefix as a CIK and may fail for filing-agent accessions; provide `ticker/accession` in that case. Historic submission-file lookup is supported. Network requests identify the requester, are spaced, and use bounded retries. Filing bytes are cached and hashed; cache hits are checked against their stored content hash. See [SEC access guidance](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data).

Explicit fiscal periods are required. The UI's optional period field or CLI `--periods FY2025 FY2024` can supply them. Conflicting period inputs return `NEEDS_INPUT`. Missing entities/periods or ambiguous semantics must not be silently guessed. The selected filing supplies entity context to the model planner.

Supported formulas: revenue growth, operating margin, operating-margin change, current ratio, current-ratio change, gross margin, gross-margin change, R&D intensity (`rd_intensity`), inventory growth and accounts-receivable growth. Gross margin requires a gross-profit row; deriving an absent gross-profit row from revenue and cost is not currently implemented.

The metric menu constructs a deterministic formula/dependency plan and bypasses model planning. Supply the explicit fiscal years in the period field. A component-by-year input inventory is checked before retrieval/model verification; all components must subsequently pass verification and guards before the registered Python calculator runs once. The calculator returns each year's metric, absolute difference, relative percentage difference and direction. A zero previous metric makes relative percentage change undefined, without invalidating a defined absolute difference. Qwen never calculates or compares the numeric result.

**Qwen can be switched off** using **Enable Qwen agents** in the sidebar, `FFA_QWEN_ENABLED=false`, or CLI `--no-qwen`. This disables decoder planning, verification and correction calls. Select a registered metric and explicit years in this mode; free-text planning returns `NEEDS_INPUT`. FinBERT retrieval stays enabled. Evidence must satisfy deterministic registered concept, unit, statement, period and provenance checks; ambiguous evidence still abstains. The saved result records its mode and decoder-call count. Mode changes apply to subsequent runs.

Verifier contract v2 accepts one source-ID observation per unresolved check. The JSON grammar restricts allowed IDs separately for each check; Python resolves each ID to its original text/fact and checks its filing, row binding and evidence type again. An unsupported scope claim must be UNCERTAIN; the literal word “consolidated” is not required in every nearby excerpt. Invalid reviews get one bounded contract-repair attempt, then an operational error without evidence expansion. Optional accounting certificates cannot become model prerequisites. The UI exposes the actual system prompts and run-specific contract/checks. See [Qwen responsibilities and verifier contract](QWEN_VERIFIER_CONTRACT.md).

Reported labels are interpreted with their value dimension. A monetary **Gross margin** subtotal may be the reported gross-profit amount; a percentage row cannot fill that component. Python additionally checks the same-table accounting identity `gross_profit = revenue - cost_of_sales` when unique compatible source rows exist. An exact certificate is recorded with all source IDs and period checks and directly validates the concept, even with Qwen enabled. This prevents a model's label-only reinterpretation from vetoing independently reconciled source evidence. Where no certificate is available, enabled Qwen receives the canonical definition, accepted reported labels and unit/context information. No derived replacement amount is invented by this certificate.

```powershell
.venv/Scripts/python.exe -m financial_filing_agent.cli --source evaluation/fixtures/converted_apple_2026_10k.html --formula gross_margin_change --periods FY2025 FY2024 --no-qwen
```

Balance sheets often report fewer years than income statements. In the supplied converted FY2026 Apple filing, revenue has FY2024 data but the balance sheet has only FY2026/FY2025. Therefore FY2024→FY2025 current-ratio change needs an older filing. Upload a supporting same-company filing, or explicitly enable the cached same-company search checkbox. The tool selects a single filing that covers the complete formula inputs, validates company identity, retains the original requested source in the audit, and discloses any source switch. It does not silently splice incompatible facts across filings. Example:

```powershell
.venv/Scripts/python.exe -m financial_filing_agent.cli --source evaluation/fixtures/converted_apple_2026_10k.html --formula current_ratio_change --periods FY2025 FY2024 --supporting-source evaluation/fixtures/apple_2025_10k.html
```

Without complete source periods, the pipeline identifies the missing component/year cells and abstains before expensive verification. An unrelated cash-flow row containing a matching year cannot satisfy a balance-sheet requirement.

## Responsibilities and graph

| Component | Responsibility |
|---|---|
| Task Planner agent | An explicit metric uses a registered Python plan; free-text questions use Qwen to select an allowlisted formula and explicit periods. Free-text planning with Qwen disabled returns `NEEDS_INPUT`. |
| Evidence Verification agent | Python checks eligibility, registered concepts and source-backed issuer scope; Qwen reviews remaining questions through evidence IDs. A source accounting identity can certify a monetary gross-profit subtotal without Qwen. |
| Correction/Recovery agent | Filters ineligible/rejected rows, then uses Qwen or deterministic rules to select an existing evidence ID, request bounded expansion, or report no valid evidence. |
| FinBERT retrieval model | Encodes and ranks structurally eligible source rows; it is not an autonomous agent. |
| Tools | SEC/local loading, structured table/XBRL parsing, lexical signals, caches, guards, calculation and audit writes. |
| Shared state | A serializable typed record of task, source/hash, artifact references, candidates, decisions, accepted IDs, errors, budgets and timings. Models/tensors/sessions stay outside it. |
| LangGraph orchestrator | Explicit nodes/conditional edges enforce component iteration, retries, recovery, re-verification, acceptance and terminal outcomes. |
| UI and CLI | Collect requests and display the same pipeline result. Neither contains agent routing logic. |

The graph has 14 application nodes. Early eligibility is implemented inside existing nodes; it did not add a new LangGraph node. This overview labels those nodes and omits repetitive terminal exits for readability. See the [system structure and node map](reports/CURRENT_SYSTEM_STRUCTURE.md) and the [complete Mermaid export from LangGraph](reports/current_langgraph.mmd).

Three of those nodes host the three agent roles: **Planner Agent** in `plan_task`, **Verifier Agent** in `verify`, and **Corrector Agent** in `correct`. Each agent has its own instructions, inputs and validated output schema. They share the local model service, while LangGraph decides which role runs next. Explicit metric selection bypasses the Planner Agent; successful verification and guards bypass the Corrector Agent. With agents disabled, the corresponding stages use registered Python rules or request more input.

```mermaid
flowchart TD
  startNode([START]) --> validateRequest["validate_request: validate inputs"]
  validateRequest --> loadFiling["load_filing: local or SEC HTML"]
  loadFiling --> planTask["plan_task: Planner Agent or registered metric plan"]
  planTask --> buildEvidence["build_evidence: parse tables and XBRL"]
  buildEvidence --> checkInputs["check_inputs: years and allowed supporting sources"]
  checkInputs --> retrieveComponent["retrieve_component: eligibility then FinBERT ranking"]
  retrieveComponent --> assessSufficiency{"assess_sufficiency"}
  assessSufficiency -->|"Supported or unresolved after expansion"| verifyEvidence["verify: eligibility recheck then Verifier Agent or rules"]
  assessSufficiency -->|"Unresolved and budget remains"| expandSearch["expand_search: eligibility then full ranking"]
  expandSearch --> assessSufficiency
  verifyEvidence -->|PASS| guardEvidence["guard: verified selection and nonzero denominator"]
  verifyEvidence -->|"Rejected and budget remains"| correctEvidence["correct: filter then Corrector Agent or rules"]
  guardEvidence -->|"Failed and budget remains"| correctEvidence
  correctEvidence -->|Replacement| verifyEvidence
  correctEvidence -->|"Allowed expansion"| expandSearch
  correctEvidence -->|"Bounded retry"| correctEvidence
  guardEvidence -->|Accepted| nextComponent{"next_component"}
  nextComponent -->|"More components"| retrieveComponent
  nextComponent -->|"All accepted"| calculateResult["calculate: cross-input checks and Python arithmetic"]
  calculateResult -->|"Recoverable incompatibility and budget"| correctEvidence
  calculateResult -->|SUCCESS| finishRun["finish: final response"]
  finishRun --> endNode([END])
  classDef early fill:#E6F3FF,stroke:#2878B5
  classDef agent fill:#EEE5FF,stroke:#7952B3
  class retrieveComponent,expandSearch early
  class planTask,verifyEvidence,correctEvidence agent
```

Purple nodes host the three agent roles; their model calls depend on the selected mode and request. Blue retrieval nodes apply early structural eligibility, and the verification/correction stages recheck eligibility too. Invalid units, restricted XBRL dimensions, incompatible periods and other failed source constraints are excluded before encoding/ranking or model review. If no eligible/ranked rows remain, retrieval ends with `INSUFFICIENT_EVIDENCE`. After verification, the guard checks only that the exact selected ID has the latest PASS and that required denominators are present and nonzero. It relies on the eligibility checks before verification. The calculator retains its input contract, including verified IDs and compatibility across accepted components.

Every node before `finish` can terminate through `finish` when a final status is set; these repeated arrows are omitted above. `NEEDS_INPUT`, `UNSUPPORTED_TASK`, `INSUFFICIENT_EVIDENCE` and `ERROR` are statuses, not separate graph nodes. Missing years can trigger same-company supporting-source selection inside `check_inputs`; only explicitly supplied sources or an opted-in cache search are used. Audit snapshots and progress events are produced around node execution, with a final audit save after the graph returns.

Operational failures at any stage route to `ERROR`. No unconstrained ReAct loop is used. A maximum of two correction rounds and one expansion applies per component by default; correction candidate chunks and HTTP retries also have explicit limits. Every replacement is reverified and guarded. A rejected row is never restored as accepted evidence merely because recovery failed.

## Evidence and sufficiency policy

Source-backed scope assessment uses preserved statement headings, row-group headings, issuer/context IDs, dimensions and associated consolidation declarations. A primary statement with issuer-matching XBRL contexts and a consolidation declaration or explicit consolidated heading can establish scope. A repeated note row can inherit that scope only through exact same-filing XBRL fact identities. Empty dimensions alone are insufficient. Explicitly restricted scope is rejected; unresolved scope remains open. With agents enabled, an all-resolved review records `deterministic_source_scope` without a model call. Unchanged UNCERTAIN evidence is not retried; new supporting evidence can make it eligible for another bounded review.

The parser preserves real statement rows and source/table/row/cell positions rather than flattening the entire filing into prose. Inline XBRL facts retain concepts, contexts, periods, scales, currency, dimensions, raw values and normalized values. Plain HTML uses explicit year/date header columns and currency/scale context. Converted HTML with dollar symbols can establish a monetary table basis without establishing an ISO currency code. For the registered dimensionless percentages/ratios, an unspecified currency can cancel only when all relevant facts share that table basis; no USD denomination is inferred from `$`. Mixed identified/unidentified currencies, conflicting currencies, unrelated source bases, genuinely missing units and ambiguous duplicate facts still fail validation. Equal values across years remain distinct. DOM table indices differ from the notebook's pandas table indices; source IDs include the filing hash.

Parser `ixbrl-table-v9` safely rejects incomplete numeric fragments such as `(4,901` without crashing retrieval-text construction. Inline XBRL signs and scales remain authoritative. Plain HTML can reconstruct split parentheses only within one row and one explicitly mapped fiscal-year column group with one numeric payload; original cells and the numeric cell position remain recorded. Incomplete groups, multiple payloads, cells spanning different years and unsupported cross-row joins remain unresolved. Explicit ISO or English month/day/four-digit-year filing dates are parsed without supplying a year from today's date; comma spacing does not change the year. The parser version invalidates older evidence/embedding caches, and filing metadata is reread from cached source HTML.

Hybrid retrieval exposes FinBERT cosine, lexical similarity, exact normalized-label support, expected statement, XBRL concept support, period availability and numeric availability. Default fusion is `1.0*cosine + 0.25*lexical + 0.25*xbrl`. All signals and weights are recorded. These defaults are transparent heuristics, not calibrated confidence. Diagnostics include top scores, margin, method agreement and candidate availability.

Registered revenue metrics use the reported consolidated revenue total. The labels in `config/financial_concepts.py` distinguish reported revenue totals from net sales. When a structurally supported revenue total is separately reported for any requested year, net sales cannot replace it, even if net sales has a supported XBRL tag. Missing years or conflicting reported totals cause abstention instead of a switch in basis. Net sales remains supported when no separate revenue total is found for the requested periods. This semantic policy filters retrieval/expansion and correction candidates and is enforced before agent verification; it is separate from structural eligibility. Decisions and excluded IDs are recorded under `revenue_basis` in retrieval diagnostics and concept assessments, and the selected basis is included in the final response. No values are synthesized or chosen by size. A separate net-sales metric is not currently exposed.

The input inventory checks missing statement-period coverage before retrieval. Structural eligibility then removes incompatible rows before FinBERT encoding; per-row failures and counts are retained in retrieval diagnostics while original rows remain in the evidence artifact. The sufficiency gate returns `SUFFICIENT`, `UNCERTAIN` or `INSUFFICIENT` for the remaining candidates. Strong structural and concept support permits verification; it never directly authorizes arithmetic. Unresolved retrieval may trigger broader search once, with the same eligibility constraints. Ambiguous concepts after expansion are assessed by the verifier; exhausted insufficient evidence produces abstention. Acceptance requires prior structural eligibility, a validated PASS for the selected row and any required nonzero denominator. The guard does not repeat structural eligibility or maintain a separate validation certificate. Final calculation checks complete accepted coverage, verified IDs, matching periods and currencies, and defined arithmetic.

Output status is `SUCCESS`, `INSUFFICIENT_EVIDENCE`, `NEEDS_INPUT`, `UNSUPPORTED_TASK` or `ERROR`. Abstention means support was not established in the searched scopes; it does not prove that the entire filing lacks the evidence. Missing any required component suppresses the final derived number. No raw cosine score is interpreted as a probability.

Evidence embeddings are cached by filing hash, parser version, actual encoder revision, tokenizer/preprocessing, token limit and evidence-text hash. Subsequent questions reuse parsed evidence and cached row vectors, encoding only the query for unchanged rows. Expansion exposes the full eligible ranking beyond the initial top-k, rechecking eligibility and reusing cached row vectors.

## Audit and evaluation

Each request writes `artifacts/runs/<request_id>/audit.json` and an immutable-for-that-run evidence artifact. The audit includes config/hash, source/hash, timestamps, model names/revisions/digest where available, prompt/formula versions, graph transitions, structured decisions, model request/response content, guards, inputs, arithmetic, timings and counts. It does not request or retain a model's separate hidden thinking channel. Failed calls and partial runs are retained. The UI exposes concise reasons and expandable panels; the on-disk audit includes full model-call records.

The UI also displays live graph-stage starts and completions, including candidate counts, verification/guard outcomes and step durations. Windows audit replacement failures receive bounded retries; if the canonical filename remains locked, the result points to a complete `audit-recovery-*.json` snapshot. If no audit snapshot can be written, the run returns an explicit `ERROR` rather than a Python traceback or a financial answer. See [the runtime reliability fix](RUNTIME_RELIABILITY_FIX.md).

Runtime schemas contain no gold aliases, expected answers, correctness flags or tolerances. External evaluation joins those only after execution. `evaluation/fixtures/notebook_snapshot.json` freezes selected notebook source and saved observations, including its final clean-process error. Apple is development material only. The original study's conditional candidate recall and privileged alias benchmark caveats remain in the architecture plan and snapshot.

```powershell
.venv/Scripts/python.exe -m pytest -q --basetemp artifacts/test-temp

# Real encoder CPU parity plus CUDA when available; requires cached/downloadable weights
$env:FFA_RUN_LIVE='1'
$env:HF_HUB_OFFLINE='1'  # omit when weights must first be downloaded
.venv/Scripts/python.exe -m pytest tests/test_finbert.py -q --basetemp artifacts/live-test-temp
```

Tests cover contracts, all ten formulas, provenance, equal/zero/small/negative values, Apple calculation parity, missing periods/concepts, guard and repair failures, unknown evidence IDs, decoder/network errors, cache reuse/invalidation, fresh-process CLI/demo startup and Streamlit form submission. Live encoder tests compare batched output to the notebook's original single-text pooling and saved cosine scores; CUDA tests skip when unavailable. Scripted demonstrations test routing and do not estimate model accuracy.

## Repository tree

```text
SEC_Agent/
  app.py
  README.md
  IMPLEMENTATION_REPORT.md
  ARCHITECTURE_AND_MIGRATION_PLAN.md
  pyproject.toml
  requirements-lock.txt
  .env.example
  config/research.json
  src/financial_filing_agent/
    cli.py
    config/{settings,prompts,formulas,financial_concepts}.py
    schemas/{state,evidence,task,results}.py
    models/{finbert,local_decoder}.py
    tools/{sec_client,filing_loader,filing_parser,html,xbrl,evidence_builder,numeric_parser,validation,calculator}.py
    retrieval/{finbert_retriever,lexical_retriever,hybrid_retriever,sufficiency}.py
    agents/{planner,verifier,corrector}.py
    graph/{workflow,routing}.py
    services/{pipeline,audit,cache}.py
    ui/{streamlit_app,components}.py
  evaluation/
    fixtures/{apple_2025_10k.html,demo.html,notebook_snapshot.json}
    fixtures.py
    doubles.py
    metrics.py
    runner.py
    live_demo.py
  scripts/freeze_development.py
  tests/{test_application,test_finbert,test_ui}.py
  artifacts/  # ignored runtime/cache/test output
```

## Known limits

Table classification and runtime concept mappings are deliberately bounded; arbitrary SEC layouts, unusual Inline XBRL transformations, restatements, noncalendar fiscal-year naming and dimensional facts require additional evaluation. Fiscal focus/end-date metadata is used when available; calendar-end-year inference without it may be insufficient. Unsupported transformations remain unresolved. The parser does not currently reconcile duplicate facts or support PDF/image filings. Table-heading heuristics can miss a statement and should then abstain. External URL access is restricted to SEC HTTPS hosts.

The three Qwen roles share one decoder and may make correlated mistakes. Mechanical guards cannot prove accounting semantics. Hybrid weights, concept mappings and sufficiency policy have not been calibrated on a held-out dataset. Correction covers a bounded set of parsed rows and may leave uninspected chunks; the audit warns when the chunk budget limits coverage. The application does not guarantee exhaustive full-filing retrieval. This is a runnable research application, not validated general financial advice or a claim of safeguard effectiveness.

The original exact-alias benchmark and FinBERT dual-view verifier are retained as historical notebook observations, not additional default production agents. A full held-out benchmark harness with uncertainty estimates remains future research; `evaluation.metrics` and the shared pipeline provide the evaluation boundary.
