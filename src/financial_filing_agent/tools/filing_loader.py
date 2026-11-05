from pathlib import Path
from .html import parse_html
from ..schemas.evidence import Filing
from ..services.cache import digest, atomic_json
from .sec_client import SECClient


def load_filing(source, settings):
    cache = settings.artifact_dir / "filings"
    metadata = {}
    path = Path(source)
    if not source.startswith("https://") and path.is_file():
        raw = path.read_bytes()
    else:
        if not source.startswith("https://") and (path.suffix.lower() in {".htm", ".html"} or "\\" in source):
            raise FileNotFoundError("Local filing does not exist: " + source)
        client = SECClient(settings)
        if not source.startswith("https://"):
            source, metadata = client.resolve(source)
        index = cache / (digest(source) + ".json")
        if index.exists():
            import json
            record = json.loads(index.read_text(encoding="utf-8"))
            cached = cache / (record["content_hash"] + ".html")
            raw = cached.read_bytes()
            if digest(raw) != record["content_hash"]:
                raise ValueError("Cached filing content hash mismatch")
            metadata = record["metadata"]
        else:
            raw = client.get(source)
    content_hash = digest(raw)
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / (content_hash + ".html")
    if not cached.exists():
        cached.write_bytes(raw)
    html = raw.decode("utf-8-sig", errors="replace")
    soup = parse_html(html)
    # Converted HTML often retains a descriptive title but strips DEI tags.
    # Recover explicit source metadata without guessing an entity from prose.
    if soup.title:
        import re
        title = soup.title.get_text(" ", strip=True)
        match = re.match(r"^(.*?)\s*\(Form:\s*([^,)]+)", title, re.I)
        if match:
            metadata.setdefault("entity", match.group(1).strip())
            metadata.setdefault("form", match.group(2).strip())
    for name, key in [("EntityRegistrantName", "entity"), ("DocumentFiscalYearFocus", "fiscal_year"), ("DocumentPeriodEndDate", "period_end"), ("DocumentType", "form"), ("EntityCentralIndexKey", "cik")]:
        tag = soup.find(attrs={"name": lambda v: v and v.split(":")[-1] == name})
        if tag:
            metadata[key] = tag.get_text(strip=True)
            if key == "period_end":
                from dateutil.parser import parse
                try:
                    metadata[key] = parse(metadata[key].replace("\ufffd", " ").replace("\xa0", " ")).date().isoformat()
                except ValueError:
                    metadata[key] = None
    atomic_json(cache / (digest(source) + ".json"), {"content_hash": content_hash, "metadata": metadata})
    return Filing(source=source, content_hash=content_hash, local_path=str(cached.resolve()), metadata=metadata), html
