"""Acquire a frozen evaluation corpus; never substitute sources during replay."""
import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

from financial_filing_agent.config.settings import Settings
from financial_filing_agent.services.cache import atomic_json
from financial_filing_agent.tools.html import parse_html
from financial_filing_agent.tools.sec_client import SECClient


def validate_html(raw, spec):
    soup = parse_html(raw.decode("utf-8-sig", errors="replace"))
    metadata = {}
    for name in ("EntityCentralIndexKey", "DocumentType", "DocumentFiscalYearFocus", "DocumentPeriodEndDate"):
        tags = soup.find_all(attrs={"name": lambda v: v and v.split(":")[-1] == name})
        values = list(dict.fromkeys(tag.get_text(strip=True) for tag in tags))
        if len(values) != 1:
            raise ValueError(f"Missing or ambiguous filing identity: {name}")
        metadata[name] = values[0]
    date_text = metadata["DocumentPeriodEndDate"]
    try:
        period_end = datetime.fromisoformat(date_text).date().isoformat()
    except ValueError:
        normalized = " ".join(date_text.replace(",", " ").split())
        period_end = datetime.strptime(normalized, "%B %d %Y").date().isoformat()
    if (int(metadata["EntityCentralIndexKey"]) != spec["cik"] or metadata["DocumentType"] != "10-K"
            or int(metadata["DocumentFiscalYearFocus"]) != spec["fiscal_year"]
            or period_end != spec["period_end"]):
        raise ValueError("Downloaded filing identity does not match manifest")
    if not soup.find("table") or not soup.find(attrs={"contextref": True}):
        raise ValueError("Expected financial tables and inline XBRL facts")
    return metadata


def mirror_url(spec):
    return "https://barchart.websol.barchart.com/?" + urlencode({
        "accession_num": spec["accession"], "cik": spec["cik"], "lang": "en",
        "module": "secFilings", "override": 1, "symbol": spec["ticker"], "type": "HTML"})


def acquire(specs, output_dir, settings=None, allow_mirror=False):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = settings or Settings()
    client = SECClient(settings)
    session = requests.Session()
    output = output_dir / "manifest.json"
    previous = {r["ticker"]: r for r in json.loads(output.read_text())["filings"]} if output.exists() else {}
    records, last_request = [], 0.0
    contact = settings.sec_user_agent.lower()
    contact_valid = "@" in contact and "example.com" not in contact and "your-email" not in contact
    for spec in specs:
        record = {**spec, "attempts": [], "acquired_at": datetime.now(timezone.utc).isoformat()}
        try:
            old = previous.get(spec["ticker"], {})
            local = Path(old.get("local_path") or spec.get("existing_path") or output_dir / "missing")
            if local.is_file():
                raw = local.read_bytes()
                if old.get("sha256") and hashlib.sha256(raw).hexdigest() != old["sha256"]:
                    raise ValueError("Existing corpus file hash mismatch; refusing silent replacement")
                record.update({"method": old.get("method", spec.get("existing_method", "existing_local")),
                               "download_url": old.get("download_url", spec.get("existing_download_url"))})
            else:
                raw = None
                if contact_valid:
                    time.sleep(max(0, 1 - (time.monotonic() - last_request)))
                    last_request = time.monotonic()
                    try:
                        raw = client.get(spec["sec_url"])
                        validate_html(raw, spec)
                        record.update({"method": "sec_direct", "download_url": spec["sec_url"]})
                    except (requests.RequestException, ValueError) as exc:
                        record["attempts"].append({"source": "SEC", "error_type": type(exc).__name__})
                        raw = None
                else:
                    record["attempts"].append({"source": "SEC", "error_type": "CONTACT_NOT_CONFIGURED"})
                if raw is None:
                    if not allow_mirror:
                        raise ValueError("SEC acquisition unavailable; register a local file or explicitly enable mirror fallback")
                    time.sleep(max(0, 1 - (time.monotonic() - last_request)))
                    last_request = time.monotonic()
                    url = mirror_url(spec)
                    response = session.get(url, timeout=45)
                    response.raise_for_status()
                    raw = response.content
                    record.update({"method": "barchart_mirror", "download_url": url})
            record["metadata"] = validate_html(raw, spec)
            destination = output_dir / f"{spec['ticker']}_FY{spec['fiscal_year']}.html"
            destination.write_bytes(raw)
            record.update({"status": "AVAILABLE", "local_path": str(destination.resolve()),
                           "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        except (OSError, ValueError, requests.RequestException) as exc:
            record.update({"status": "ACQUISITION_FAILED", "error_type": type(exc).__name__,
                           "error": str(exc) if not isinstance(exc, requests.RequestException) else "HTTP/download failure"})
        records.append(record)
        with (output_dir / "acquisition.jsonl").open("a", encoding="utf-8") as history:
            history.write(json.dumps(record) + "\n")
        atomic_json(output, {"schema_version": 1, "filings": records})
        print(json.dumps({"ticker": spec["ticker"], "status": record["status"], "method": record.get("method"),
                          "error": record.get("error")}), flush=True)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="evaluation/cases/pilot_manifest.json")
    parser.add_argument("--output", default="artifacts/multi-company/corpus")
    parser.add_argument("--allow-mirror", action="store_true")
    args = parser.parse_args()
    records = acquire(json.loads(Path(args.manifest).read_text())["filings"], args.output, allow_mirror=args.allow_mirror)
    if any(r["status"] != "AVAILABLE" for r in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
