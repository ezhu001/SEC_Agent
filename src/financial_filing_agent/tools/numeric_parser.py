import math
import re


def number(text: str) -> float | None:
    """Parse a single financial cell, retaining zero and small amounts."""
    s = text.strip().replace("\u2212", "-").replace("\xa0", " ")
    if s in {"—", "–", "-"}:
        return 0.0
    s = re.sub(r"[$,\s]", "", s)
    negative = s.startswith("(") and s.endswith(")")
    if negative:
        s = s[1:-1]
    if not re.fullmatch(r"-?\d+(?:\.\d+)?", s):
        return None
    value = float(s)
    if not math.isfinite(value):
        return None
    return -abs(value) if negative else value


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
