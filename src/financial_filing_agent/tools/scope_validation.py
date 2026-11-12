"""Source extraction and conservative issuer-scope assessment; no model decisions."""
import json
import re
import hashlib

from ..schemas.evidence import SourceText
from .numeric_parser import normalize


HEADING = re.compile(
    r"(?:consolidated\s+)?(?:balance\s+sheets?|statements?\s+of\s+(?:income|operations|earnings)|(?:income|operations|earnings)\s+statements?)", re.I)
DECLARATION = re.compile(
    r"\b(?:the|our|these)\s+(?:accompanying\s+)?consolidated\s+financial\s+statements\s+"
    r"(?:include|reflect|comprise)\b.{0,450}?\bsubsidiar(?:y|ies)\b", re.I)
RESTRICTED = re.compile(r"\b(?:parent[- ]only|parent company|subsidiary|subsidiaries|segment|segments)\b", re.I)


def scope_sources(soup, filing):
    headings, declarations = [], []
    seen = set()
    for index, tag in enumerate(soup.find_all(True)):
        if tag.name not in {"p", "div", "td", "h1", "h2", "h3", "h4"}:
            continue
        # Bound work on wrappers containing entire document sections.
        parts = []
        for part in tag.stripped_strings:
            parts.append(part)
            if sum(map(len, parts)) > 1200:
                break
        if sum(map(len, parts)) > 1200:
            continue
        # Adjacent inline spans can split a word: INC + OME STATEMENTS.
        text = " ".join(tag.get_text("", strip=False).split())
        citation = SourceText(text=text, locator=f"element:{index}", filing_hash=filing.content_hash)
        title = HEADING.match(text)
        suffix = text[title.end():] if title else ""
        units_only = re.fullmatch(r"[\s,(]*(?:in\s+)?(?:USD|millions|thousands|dollars)(?:[\s,()]*(?:in\s+)?(?:USD|millions|thousands|dollars))*[\s,().]*", suffix, re.I)
        if title and (not suffix or units_only):
            headings.append((tag, citation.model_copy(update={"text": title.group()})))
        match = DECLARATION.search(text)
        if match and match.group() not in seen:
            seen.add(match.group())
            declarations.append(citation.model_copy(update={"text": match.group()}))
    return headings, declarations


def table_heading(table, nearby, headings):
    candidates = []
    previous, size = set(), 0
    for tag in table.previous_elements:
        previous.add(id(tag))
        if getattr(tag, "name", None) == "table":
            break
        if isinstance(tag, str):
            size += len(tag)
        if size > 2500:
            break
    for tag, citation in headings:
        if id(tag) in previous and re.sub(r"\s", "", citation.text) in re.sub(r"\s", "", nearby[-500:]):
            candidates.append(citation)
        elif tag.find_parent("table") is table and table.get_text(" ", strip=True).startswith(citation.text):
            candidates.append(citation)
    return candidates[-1] if candidates else None


def _facts(row, periods):
    selected = [f for f in row.facts if f.period in periods]
    return selected if all(sum(f.period == p for f in selected) == 1 for p in periods) else []


def fact_identity(row, periods):
    facts = _facts(row, periods)
    if not facts or any(not f.context_id or not f.entity_identifier or not f.concept for f in facts):
        return None
    return sorted(json.dumps({k: f.model_dump()[k] for k in (
        "period", "value", "concept", "context_id", "entity_identifier", "entity_scheme", "currency",
        "unit", "scale", "start", "end", "instant", "dimensions")}, sort_keys=True) for f in facts)


def _issuer_matches(facts, metadata):
    cik = str(metadata.get("cik", "")).lstrip("0")
    return bool(cik and facts) and all(
        f.entity_identifier and f.entity_identifier.lstrip("0") == cik
        and f.entity_scheme and f.entity_scheme.rstrip("/").lower() == "http://www.sec.gov/cik"
        for f in facts)


def _primary(row, periods, metadata):
    facts = _facts(row, periods)
    heading = row.statement_heading
    if not facts or any(f.dimensions for f in facts) or not heading or heading.filing_hash != row.filing_hash:
        return None
    if RESTRICTED.search(row.row_group_heading.text if row.row_group_heading else ""):
        return None
    expected = "balance" if "balance" in heading.text.lower() else "operations"
    if expected != row.statement:
        return None
    issuer = normalize(metadata.get("entity", ""))
    def issuer_name(text):
        match = re.search(r"\baccounts of (.*?) and\b", normalize(text))
        if not match or not issuer:
            return False
        legal_suffix = r"(?: (?:inc|incorporated|corp|corporation|limited|ltd|plc))+$"
        return re.sub(legal_suffix, "", match.group(1)) == re.sub(legal_suffix, "", issuer)
    declarations = [s for s in row.scope_declarations if s.filing_hash == row.filing_hash
                    and issuer_name(s.text) and DECLARATION.search(s.text)]
    has_contexts = any(f.context_id for f in facts)
    if has_contexts and not _issuer_matches(facts, metadata):
        return None
    explicit_heading = "consolidated" in heading.text.lower()
    if not (has_contexts and (explicit_heading or declarations) or not has_contexts and explicit_heading and declarations):
        return None
    return [heading, *declarations]


def assess_scope(row, rows, periods, metadata):
    facts = _facts(row, periods)
    sources = [s.model_dump() for s in [row.statement_heading, row.row_group_heading] if s and s.filing_hash == row.filing_hash]
    result = {"status": "UNRESOLVED", "reason": "Source evidence does not establish issuer-wide scope", "sources": sources,
              "related_evidence_ids": []}
    if not facts:
        return result
    if any(f.dimensions for f in facts) or RESTRICTED.search(row.row_group_heading.text if row.row_group_heading else ""):
        return {**result, "status": "RESTRICTED", "reason": "Source context or row group identifies restricted scope"}
    cik = str(metadata.get("cik", "")).lstrip("0")
    if cik and any(f.entity_identifier and f.entity_scheme and f.entity_scheme.rstrip("/").lower() == "http://www.sec.gov/cik"
                   and f.entity_identifier.lstrip("0") != cik for f in facts):
        return {**result, "status": "RESTRICTED", "reason": "XBRL entity does not match the filing issuer"}
    primary = _primary(row, periods, metadata)
    if primary:
        return {**result, "status": "ESTABLISHED", "reason": "Issuer statement, consolidation declaration and source contexts agree",
                "sources": [s.model_dump() for s in primary]}
    identity = fact_identity(row, periods)
    if identity:
        for other in rows:
            if other.evidence_id == row.evidence_id or other.filing_hash != row.filing_hash:
                continue
            support = _primary(other, periods, metadata)
            if support and fact_identity(other, periods) == identity:
                return {**result, "status": "ESTABLISHED", "reason": "Exact XBRL facts repeat an established issuer statement row",
                        "sources": [s.model_dump() for s in support], "related_evidence_ids": [other.evidence_id]}
    return result


def scope_fingerprint(row, assessment, metadata):
    evidence = {"assessment": assessment, "row": row.model_dump(mode="json"),
                "issuer": {k: metadata.get(k) for k in ("entity", "cik")}}
    return hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
