from .numeric_parser import number
from ..schemas.evidence import Fact


def local(tag):
    return tag.name.split(":")[-1].lower() if tag.name else ""


def extract_contexts(soup):
    contexts, units = {}, {}
    for node in soup.find_all(lambda t: local(t) == "context"):
        def value(name):
            n = node.find(lambda t: local(t) == name)
            return n.get_text(strip=True) if n else None
        dimensions = {t.get("dimension", "unknown"): t.get_text(strip=True)
                      for t in node.find_all(lambda t: local(t) in {"explicitmember", "typedmember"})}
        contexts[node.get("id")] = dict(start=value("startdate"), end=value("enddate") or value("instant"),
                                          instant=value("instant") is not None, dimensions=dimensions)
    for node in soup.find_all(lambda t: local(t) == "unit"):
        measures = node.find_all(lambda t: local(t) == "measure")
        units[node.get("id")] = measures[0].get_text(strip=True).split(":")[-1] if len(measures) == 1 else None
    return contexts, units


def inline_fact(node, contexts, units, cell):
    ctx = contexts.get(node.get("contextref"), {})
    raw = node.get_text(" ", strip=True)
    value = number(raw)
    end = ctx.get("end")
    if value is None or not end or node.get("xsi:nil") == "true":
        return None
    # Unsupported transformations are left unresolved rather than guessed.
    fmt = node.get("format", "").split(":")[-1].lower()
    if fmt and fmt not in {"num-dot-decimal", "numdotdecimal", "num-comma-dot", "zerodash", "numdash"}:
        return None
    scale = int(node.get("scale", "0"))
    if abs(scale) > 12:
        return None
    if node.get("sign") == "-":
        value = -abs(value)
    unit = units.get(node.get("unitref"))
    currency = unit if unit and len(unit) == 3 and unit.isupper() else None
    return Fact(period="FY" + end[:4], value=value * 10 ** scale, raw_value=raw,
                unit="currency" if currency else unit, currency=currency, scale=scale,
                concept=node.get("name"), context_id=node.get("contextref"), cell=cell, **ctx)
