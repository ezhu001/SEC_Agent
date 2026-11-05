from datetime import datetime, timezone
from pathlib import Path
import uuid
from .cache import atomic_json


class Audit:
    def __init__(self, settings, request_id):
        self.directory = settings.artifact_dir / "runs" / request_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.last_path = None
        self.warnings = []

    def event(self, node, seconds, details):
        return {"node": node, "timestamp": datetime.now(timezone.utc).isoformat(),
                "seconds": seconds, "details": details}

    def save(self, state, decoder_calls):
        path = self.directory / "audit.json"
        def payload(target):
            return {"state": {**state, "audit_path": str(target.resolve()), "audit_complete": state.get("audit_complete", True),
                              "warnings": list(dict.fromkeys(state["warnings"] + self.warnings))},
                    "decoder_calls": decoder_calls}
        try:
            atomic_json(path, payload(path))
        except OSError as exc:
            # Do not destroy/overwrite the last good audit if the canonical
            # filename remains locked. Save this full snapshot under a new name.
            path = self.directory / ("audit-recovery-" + uuid.uuid4().hex[:12] + ".json")
            warning = f"Canonical audit file could not be replaced ({type(exc).__name__}); a complete recovery snapshot was saved."
            if warning not in self.warnings:
                self.warnings.append(warning)
            atomic_json(path, payload(path))
        self.last_path = str(path.resolve())
        return self.last_path
