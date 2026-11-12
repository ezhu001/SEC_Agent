import hashlib
import json
from pathlib import Path

import pytest

from evaluation.acquire_corpus import acquire, validate_html
from financial_filing_agent.config.settings import Settings


SPEC = {"ticker": "TEST", "cik": 123, "fiscal_year": 2025, "period_end": "2025-12-31", "accession": "test", "sec_url": "https://www.sec.gov/test"}
HTML = b'''<html><ix:nonNumeric name="dei:EntityCentralIndexKey">123</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentType">10-K</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentFiscalYearFocus">2025</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentPeriodEndDate">2025-12-31</ix:nonNumeric>
<table><tr><td><ix:nonFraction contextRef="c">1</ix:nonFraction></td></tr></table></html>'''


def test_rejects_error_page_and_wrong_company():
    with pytest.raises(ValueError):
        validate_html(b"<html>Forbidden</html>", SPEC)
    with pytest.raises(ValueError, match="identity"):
        validate_html(HTML, {**SPEC, "cik": 456})


def test_explicit_year_survives_date_without_space_after_comma():
    html = HTML.replace(b"2025-12-31", b"December 31,2025")
    assert validate_html(html, SPEC)["DocumentPeriodEndDate"] == "December 31,2025"


def test_local_registration_resume_and_hash_tampering(tmp_path, monkeypatch):
    source = tmp_path / "source.html"
    source.write_bytes(HTML)
    monkeypatch.setattr("requests.Session.get", lambda *a, **k: pytest.fail("No network permitted"))
    settings = Settings(sec_user_agent="")
    output = tmp_path / "corpus"
    first = acquire([{**SPEC, "existing_path": str(source)}], output, settings)[0]
    assert first["status"] == "AVAILABLE"
    assert first["sha256"] == hashlib.sha256(HTML).hexdigest()
    assert acquire([SPEC], output, settings)[0]["status"] == "AVAILABLE"
    Path(first["local_path"]).write_bytes(b"corrupt")
    assert acquire([SPEC], output, settings)[0]["status"] == "ACQUISITION_FAILED"


def test_missing_contact_records_failure_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.Session.get", lambda *a, **k: pytest.fail("No network permitted"))
    record = acquire([SPEC], tmp_path, Settings(sec_user_agent=""))[0]
    assert record["status"] == "ACQUISITION_FAILED"
    assert record["attempts"][0]["error_type"] == "CONTACT_NOT_CONFIGURED"
    assert json.loads((tmp_path / "manifest.json").read_text())["filings"][0]["status"] == record["status"]
