import json
from pathlib import Path
from .filing_loader import load_filing
from .filing_parser import parse_filing
from .input_inventory import inventory
from .numeric_parser import normalize


def same_entity(a, b):
    if a.get("cik") and b.get("cik"):
        return str(a["cik"]).lstrip("0") == str(b["cik"]).lstrip("0")
    return bool(a.get("entity") and b.get("entity") and normalize(a["entity"]) == normalize(b["entity"]))


def find_complete_filing(primary, plan, settings, sources, use_cache=False):
    candidates = list(sources)
    if use_cache:
        directory = settings.artifact_dir / "filings"
        for index in sorted(directory.glob("*.json"))[:100]:
            try:
                record = json.loads(index.read_text(encoding="utf-8"))
                if same_entity(primary.metadata, record.get("metadata", {})):
                    candidates.append(str(directory / (record["content_hash"] + ".html")))
            except (OSError, ValueError, KeyError):
                continue
    seen = {primary.content_hash}
    attempts = []
    for source in list(dict.fromkeys(candidates))[:50]:
        try:
            filing, html = load_filing(source, settings)
            if filing.content_hash in seen:
                continue
            seen.add(filing.content_hash)
            if not same_entity(primary.metadata, filing.metadata):
                attempts.append({"source": source, "reason": "Company identity does not match"})
                continue
            rows, statements = parse_filing(html, filing)
            cells = inventory(rows, plan)
            attempts.append({"source": source, "inventory": cells})
            if all(cell["status"] == "FOUND" for cell in cells):
                return (filing, rows, statements), attempts
        except (OSError, ValueError) as exc:
            attempts.append({"source": source, "error": str(exc)})
    return None, attempts
