# Windows audit persistence and live progress correction

The reported exception had two causes. `os.replace` first failed with Windows access denied while replacing an existing `audit.json`. The graph error handler then read that UTF-8 JSON with the machine's default cp1252 codec. A curly quote in the audit caused a second `UnicodeDecodeError`, hiding the original persistence failure.

The fixes are:

- All production JSON text reads explicitly use UTF-8. Graph error recovery uses the latest in-memory state and does not reread a locked or stale audit.
- Atomic replacement retries access/sharing failures a bounded six times, with a total scheduled wait below one second. Other failures are raised immediately. Temporary files are cleaned up when possible.
- A persistently locked canonical filename causes a complete snapshot to be saved as `audit-recovery-<unique>.json`. The returned result and on-disk snapshot identify the actual path, and the UI displays a warning.
- If all audit writes fail, the workflow returns a typed operational `ERROR`, suppresses the calculation result, and exposes the original failure. It does not masquerade as insufficient financial evidence or silently claim a complete audit. A last saved partial audit is identified as partial.
- Streamlit receives start/completion events directly from graph nodes. It shows the current stage before the work starts, then duration, candidate count, sufficiency decision, concise verifier/corrector reason, guard outcome and calculation result. The progress callback is outside persisted state and cannot authorize evidence or alter routing. Earlier result state is cleared when a new run starts.

Validation includes actual Windows `CreateFileW` sharing restrictions on `audit.json` during `next_component`, transient/persistent lock injection, total filesystem failure, an unwritable audit directory, Chinese and smart-quote content, forced graph failure, and UI rendering during audit failure. The full suite passed 63 tests with one unavailable-CUDA skip. After adding the explicit UI failure case, the three UI tests passed separately. Reports are under `artifacts/runtime-final.xml` and `tests/test_runtime_reliability.py` records the failure scenarios.

The original failed audit `790c0c9b65a1482eb40b4766e8f67eb7/audit.json` was successfully read with UTF-8 and was not overwritten as part of the fix. Financial evidence validation and abstention rules were not weakened by these persistence changes.
