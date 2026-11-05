import hashlib
import json
import os
import uuid
import time
from pathlib import Path


def digest(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A short sibling name avoids Windows MAX_PATH failures in long temp roots.
    temp = path.with_name(uuid.uuid4().hex[:12] + ".tmp")
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        # Windows readers, indexers and antivirus can briefly deny replacement.
        # Retry only access/sharing errors, with a finite delay budget.
        for attempt in range(6):
            try:
                os.replace(temp, path)
                return
            except OSError as exc:
                retryable = isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32, 33}
                if not retryable or attempt == 5:
                    raise
                time.sleep(min(0.025 * 2 ** attempt, 0.4))
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
