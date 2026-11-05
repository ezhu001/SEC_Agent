import re
from .numeric_parser import number


def retrieval_text(cells):
    """Notebook-style compact cells; keep equal values in distinct period cells."""
    result = []
    for raw in cells:
        text = re.sub(r"\s+", " ", raw).strip()
        if not text:
            continue
        if number(text) is not None and text not in {"-", "—", "–"}:
            text = text.replace(",", "")
        # Repeated nonnumeric display labels are formatting artifacts. Numeric
        # cells are never deduplicated across fiscal columns.
        if result and text == result[-1] and number(text) is None:
            continue
        result.append(text)
    return " | ".join(result)
