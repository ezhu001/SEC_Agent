import pytest
import requests
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.tools.sec_client import SECClient
from financial_filing_agent.tools.filing_loader import load_filing
from financial_filing_agent.tools.filing_parser import parse_filing
from financial_filing_agent.tools.validation import guard
from financial_filing_agent.schemas.evidence import Filing


def test_sec_identity_and_retry_budget(monkeypatch):
    with pytest.raises(ValueError, match="USER_AGENT"):
        SECClient(Settings(sec_user_agent="")).get("https://www.sec.gov/test")
    client = SECClient(Settings(sec_user_agent="Test test@example.com", transport_retries=1))
    calls = []
    def fail(*args, **kwargs):
        calls.append(kwargs["headers"])
        raise requests.ConnectionError("test failure")
    monkeypatch.setattr(client.session, "get", fail)
    monkeypatch.setattr("time.sleep", lambda *a: None)
    with pytest.raises(requests.ConnectionError):
        client.get("https://www.sec.gov/test")
    assert len(calls) == 2
    assert calls[0]["User-Agent"] == "Test test@example.com"


def test_ticker_accession_lookup_and_content_cache(tmp_path, monkeypatch):
    calls = []
    html = b"<html><table><tr><td>test</td></tr></table></html>"
    def get(self, url, as_json=False):
        calls.append(url)
        if "company_tickers" in url:
            return {"0": {"ticker": "TEST", "cik_str": 123}}
        if "submissions" in url:
            return {"name": "Test company", "filings": {"recent": {"accessionNumber": ["0000000123-25-000001"], "form": ["10-K"], "primaryDocument": ["test.htm"]}}}
        return html
    monkeypatch.setattr(SECClient, "get", get)
    settings = Settings(artifact_dir=tmp_path)
    first, _ = load_filing("TEST/0000000123-25-000001", settings)
    assert first.metadata["accession"] == "0000000123-25-000001"
    assert first.source.endswith("/123/000000012325000001/test.htm")
    count = len(calls)
    second, _ = load_filing(first.source, settings)
    assert first.content_hash == second.content_hash
    assert len(calls) == count


def test_non_sec_host_is_rejected():
    client = SECClient(Settings(sec_user_agent="Test test@example.com"))
    with pytest.raises(ValueError, match="Only HTTPS SEC"):
        client.get("https://example.com/file.html")


def test_single_period_header_and_reordered_columns():
    html = '''<p>Consolidated Statements of Operations in USD</p><table>
    <tr><th>Line item</th><th>2024</th><th>2025</th></tr>
    <tr><td>Total net sales</td><td>100</td><td>2025</td></tr>
    <tr><td>Operating income</td><td>10</td><td>20</td></tr></table>'''
    filing = Filing(source="test", content_hash="hash", local_path="test")
    rows, _ = parse_filing(html, filing)
    assert [(f.period, f.value) for f in rows[0].facts] == [("FY2024", 100), ("FY2025", 2025)]
    one = html.replace('<th>2024</th>', '').replace('<td>100</td>', '').replace('<td>10</td>', '')
    rows, _ = parse_filing(one, filing)
    assert rows[0].facts[0].period == "FY2025"


def test_inline_xbrl_contexts_scale_and_dimensions():
    html = '''<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>
    <xbrli:context id="ctx"><xbrli:entity><xbrli:segment><xbrldi:explicitMember dimension="Segment">Product</xbrldi:explicitMember></xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
    <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    <p>Statements of Operations</p><table><tr><td>Total revenue</td><td><ix:nonFraction name="us-gaap:Revenues" contextRef="ctx" unitRef="usd" scale="6" sign="-">2</ix:nonFraction></td></tr>
    <tr><td>Operating income</td><td>10</td></tr></table></body></html>'''
    filing = Filing(source="test", content_hash="hash", local_path="test")
    rows, _ = parse_filing(html, filing)
    fact = rows[0].facts[0]
    assert fact.value == -2_000_000
    assert fact.currency == "USD"
    assert fact.context_id == "ctx" and fact.dimensions == {"Segment": "Product"}
    result = guard(rows[0], "revenue", ["FY2024"], "hash", rows[0].evidence_id, {rows[0].evidence_id})
    assert not result["passed"] and not result["checks"]["consolidated"]
