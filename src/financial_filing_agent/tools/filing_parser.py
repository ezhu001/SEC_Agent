"""Conservative table parser. Never infers periods from numeric-value order."""
import re
from bs4 import NavigableString
from .html import parse_html
from .evidence_builder import retrieval_text
from .xbrl import extract_contexts, inline_fact, local
from .numeric_parser import number
from ..schemas.evidence import EvidenceRow, Fact


def statement_type(text, nearby=""):
    t = text.lower()
    # A cash-flow statement mentioning changes in assets/liabilities is not a
    # balance sheet. Use its nearby actual title before keyword fallbacks.
    headings = list(re.finditer(r"consolidated\s+(?:balance\s+sheets?|statements?\s+of\s+(?:cash\s+flows?|shareholders[^()]*equity|comprehensive\s+income|operations|income))", nearby[-400:], re.I))
    heading = headings[-1].group().lower() if headings else ""
    if any(x in heading for x in ("cash flow", "shareholders", "comprehensive")):
        return "other"
    if "balance sheet" in heading and "assets" in t and "liabilities" in t:
        return "balance"
    if "total current assets" in t and "total current liabilities" in t:
        return "balance"
    if any(x in t for x in ("net sales", "revenue")) and any(x in t for x in ("operating income", "net income", "gross profit")):
        return "operations"
    return "other"


def grid(table):
    """Logical HTML columns, respecting colspan and rowspan."""
    rows, pending = [], {}
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        out = {col: cell for col, (remaining, cell) in pending.items()}
        pending = {col: (remaining - 1, cell) for col, (remaining, cell) in pending.items() if remaining > 1}
        col = 0
        for cell in tr.find_all(["td", "th"], recursive=False):
            while col in out:
                col += 1
            for offset in range(min(int(cell.get("colspan", 1)), 100)):
                out[col + offset] = cell
                span = min(int(cell.get("rowspan", 1)), 100)
                if span > 1:
                    pending[col + offset] = (span - 1, cell)
            col += min(int(cell.get("colspan", 1)), 100)
        rows.append(out)
    return rows


def parse_filing(html, filing):
    soup = parse_html(html)
    contexts, units = extract_contexts(soup)
    evidence, statements = [], []
    for ti, table in enumerate(soup.find_all("table")):
        text = table.get_text(" ", strip=True)
        previous = []
        size = 0
        for node in table.previous_elements:
            if isinstance(node, NavigableString) and node.strip():
                previous.append(str(node).strip())
                size += len(str(node))
                if size >= 1500:
                    break
        nearby = " ".join(reversed(previous))[-1500:]
        kind = statement_type(text, nearby)
        if kind == "other":
            continue
        # Inline facts carry authoritative units. Plain HTML needs explicit units.
        unit_context = nearby + " " + text[:600]
        # A dollar sign or unqualified "dollars" establishes a monetary unit,
        # but does not establish USD (it might be CAD, AUD, etc.).
        codes = set(re.findall(r"\b(?:USD|CAD|AUD|EUR|GBP|JPY|CHF|CNY|HKD|SGD)\b", unit_context))
        if re.search(r"\b(?:U\.S\.|US|United States)\s+dollars\b", unit_context, re.I):
            codes.add("USD")
        currency = next(iter(codes)) if len(codes) == 1 else None
        monetary = bool(codes or "$" in text or re.search(r"\bdollars\b", unit_context, re.I))
        unit_basis = f"{filing.content_hash}:table:{ti}:monetary" if monetary and len(codes) <= 1 else None
        scale = 6 if re.search(r"in millions", unit_context, re.I) else 3 if re.search(r"in thousands", unit_context, re.I) else 0
        headers, parent = {}, ""
        for ri, cells in enumerate(grid(table)):
            distinct = list(dict.fromkeys(id(c) for c in cells.values()))
            unique = []
            for ident in distinct:
                col = next(k for k, v in cells.items() if id(v) == ident)
                unique.append((col, cells[col]))
            strings = [c.get_text(" ", strip=True) for _, c in unique]
            if not strings:
                continue
            # Header dates must be in their own cells and precede values.
            inline = [(col, n) for col, c in unique for n in c.find_all(lambda t: local(t) == "nonfraction")]
            header_years = [(col, re.fullmatch(r"(?:FY\s*)?(20\d{2})", s)) for (col, _), s in zip(unique, strings)]
            dated = [(col, re.search(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+(20\d{2})", s, re.I)) for (col, _), s in zip(unique, strings)]
            years = [(col, m.group(1)) for col, m in header_years + dated if m]
            is_header = any(c.name == "th" for _, c in unique) or not label_is_financial(strings[0])
            if years and not inline and is_header:
                for col, year in years:
                    for k, c in cells.items():
                        if c is cells[col]:
                            headers[k] = "FY" + year
                continue
            label = strings[0]
            if not label or number(label) is not None or label in {"$", "—"}:
                continue
            facts = []
            for col, node in inline:
                fact = inline_fact(node, contexts, units, col)
                if fact:
                    focus, period_end = filing.metadata.get("fiscal_year"), filing.metadata.get("period_end")
                    if focus and period_end and re.fullmatch(r"\d{4}-\d{2}-\d{2}", period_end) and fact.end:
                        fact.period = "FY" + str(int(focus) - (int(period_end[:4]) - int(fact.end[:4])))
                    facts.append(fact)
            if not inline:
                for col, cell in unique[1:]:
                    val = number(cell.get_text(" ", strip=True))
                    period = headers.get(col)
                    if val is not None and period:
                        facts.append(Fact(period=period, value=val * 10 ** scale,
                                          raw_value=cell.get_text(" ", strip=True), cell=col,
                                          currency=currency, unit="currency" if unit_basis else None,
                                          unit_basis=unit_basis,
                                          scale=scale, instant=kind == "balance"))
            if not facts:
                if label.endswith(":"):
                    parent = label
                continue
            # Retain ambiguity: validation rejects duplicate facts for a period.
            evidence.append(EvidenceRow(evidence_id=f"{filing.content_hash[:16]}:t{ti:02d}_r{ri:03d}",
                filing_hash=filing.content_hash, source=filing.source, statement=kind,
                table=ti, row=ri, label=label, text=retrieval_text(strings), raw_cells=strings,
                nearby_context=(nearby + " " + parent)[-1800:], facts=facts))
        statements.append({"table": ti, "type": kind, "context": nearby})
    return evidence, statements


def label_is_financial(label):
    """Exclude empty/date/year heading cells without mistaking amount 2025 for a date."""
    return bool(label) and not re.fullmatch(r"(?:FY\s*)?20\d{2}", label) and not re.search(r"years? ended|line item|September|December|January|June|March", label, re.I)
