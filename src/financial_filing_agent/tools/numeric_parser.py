import re


def number(text: str) -> float | None:
    """Parse a single financial cell, retaining zero and small amounts."""
    s = text.strip().replace("\u2212", "-").replace("\xa0", " ")
    if s in {"—", "–", "-"}:
        return 0.0
    s = re.sub(r"[$,\s]", "", s)
    if not re.fullmatch(r"\(?-?\d+(?:\.\d+)?\)?", s):
        return None
    return -float(s[1:-1]) if s.startswith("(") and s.endswith(")") else float(s)


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
