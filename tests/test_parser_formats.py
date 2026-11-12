import json
from pathlib import Path

import pytest

from evaluation.doubles import DemoRetriever, ScriptedDecoder
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.schemas.evidence import Filing
from financial_filing_agent.services.cache import atomic_json, digest
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.tools.evidence_builder import retrieval_text
from financial_filing_agent.tools.filing_loader import explicit_period_end, load_filing
from financial_filing_agent.tools.filing_parser import parse_filing
from financial_filing_agent.tools.numeric_parser import number
from financial_filing_agent.tools.sec_client import SECClient


@pytest.mark.parametrize("text,expected", [
    ("(4,901", None), ("4,901)", None), ("(", None), (")", None),
    ("((4,901))", None), ("(4,901)", -4901), ("(\n4,901\n)", -4901),
    ("($ 4,901)", -4901), ("(-4,901)", -4901), ("\u22124,901", -4901),
    ("9" * 400, None),
])
def test_numeric_display_fragments_and_negative_signs(text, expected):
    assert number(text) == expected


def test_retrieval_text_preserves_incomplete_display_fragments_without_crashing():
    assert retrieval_text(["Other income (expense), net", "(4,901", ")", "(1,646", ")"]) == (
        "Other income (expense), net | (4,901 | ) | (1,646 | )")


@pytest.mark.parametrize("text,expected", [
    ("June 30,2025", "2025-06-30"), ("June 30, 2025", "2025-06-30"),
    ("June\u00a030,2025", "2025-06-30"), ("2025-06-30", "2025-06-30"),
    ("Jun 30,2025", "2025-06-30"), ("February 29,2024", "2024-02-29"),
    ("June 30", None), ("June 30,25", None), ("2025-02-29", None),
    ("February 30,2025", None), ("2025-06", None), ("06/07/2025", None),
])
def test_filing_dates_require_explicit_unambiguous_calendar_dates(text, expected):
    assert explicit_period_end(text) == expected


def plain_html(first, second=("", "100", ""), dated=False):
    years = ["June 30,2025", "June 30,2024"] if dated else ["2025", "2024"]
    amounts = "".join(f"<td>{text}</td>" for text in (*first, *second))
    return f'''<p>Consolidated Statements of Operations in USD, in millions</p><table>
        <tr><th>Line item</th><th colspan="3">{years[0]}</th><th colspan="3">{years[1]}</th></tr>
        <tr><td>Total net sales</td><td></td><td>110</td><td></td><td></td><td>100</td><td></td></tr>
        <tr><td>Operating income</td>{amounts}</tr></table>'''


def parse(html):
    return parse_filing(html, Filing(source="test", content_hash="hash", local_path="test"))[0]


@pytest.mark.parametrize("cells,column", [
    (("(4,901", ")", ""), 1),
    (("(", "4,901", ")"), 2),
    (("(", "4,901)", ""), 2),
    (("($", "4,901", ")"), 2),
    (("<span>(</span><br>4,901<br><span>)</span>", "", ""), 1),
])
@pytest.mark.parametrize("dated", [False, True])
def test_split_negative_amounts_keep_period_scale_and_numeric_cell(cells, column, dated):
    row = next(r for r in parse(plain_html(cells, dated=dated)) if r.label == "Operating income")
    assert [(f.period, f.value, f.cell) for f in row.facts] == [
        ("FY2025", -4901e6, column), ("FY2024", 100e6, 5)]
    assert row.table == 0 and row.row == 2
    assert row.raw_cells[0] == "Operating income" and row.raw_cells[-2] == "100"
    assert "4,901" in row.facts[0].raw_value
    assert all(f.currency == "USD" for f in row.facts)


@pytest.mark.parametrize("cells", [("(", "4,901", ""), ("", "4,901", ")"), ("(", "4,901", "1,646)")])
def test_incomplete_or_multiple_payloads_are_not_guessed(cells):
    row = next(r for r in parse(plain_html(cells)) if r.label == "Operating income")
    assert [(f.period, f.value) for f in row.facts] == [("FY2024", 100e6)]


def test_distinct_amounts_for_the_same_period_remain_ambiguous():
    row = next(r for r in parse(plain_html(("(4,901)", "(4,901)", ""))) if r.label == "Operating income")
    assert [(f.period, f.value) for f in row.facts[:2]] == [("FY2025", -4901e6), ("FY2025", -4901e6)]


def test_parentheses_are_not_joined_across_periods_or_rows():
    html = '''<p>Consolidated Statements of Operations in USD</p><table>
        <tr><th>Line item</th><th>2025</th><th>2024</th></tr>
        <tr><td>Total net sales</td><td>110</td><td>100</td></tr>
        <tr><td>Operating income</td><td>(</td><td>4,901)</td></tr>
        <tr><td>Other income</td><td>4,901)</td><td></td></tr></table>'''
    assert [r.label for r in parse(html)] == ["Total net sales"]


def test_cell_spanning_two_years_is_not_assigned_to_one_year():
    html = '''<p>Consolidated Statements of Operations in USD</p><table>
        <tr><th>Line item</th><th>2025</th><th>2024</th></tr>
        <tr><td>Total net sales</td><td>110</td><td>100</td></tr>
        <tr><td>Operating income</td><td colspan="2">(4,901)</td></tr></table>'''
    assert [r.label for r in parse(html)] == ["Total net sales"]


def inline_html():
    return '''<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"><body>
        <ix:nonNumeric name="dei:DocumentFiscalYearFocus">2025</ix:nonNumeric>
        <ix:nonNumeric name="dei:DocumentPeriodEndDate"><span>June</span> <span>30,2025</span></ix:nonNumeric>
        <xbrli:context id="current"><xbrli:period><xbrli:startDate>2024-07-01</xbrli:startDate>
        <xbrli:endDate>2025-06-30</xbrli:endDate></xbrli:period></xbrli:context>
        <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
        <p>Consolidated Statements of Operations in USD, in millions</p><table>
        <tr><th>Line item</th><th colspan="2">2025</th></tr>
        <tr><td>Total revenue</td><td>100</td><td></td></tr>
        <tr><td>Operating income</td><td>20</td><td></td></tr>
        <tr><td>Other income (expense), net</td><td>(<ix:nonFraction
          name="us-gaap:NonoperatingIncomeExpense" contextRef="current" unitRef="usd"
          scale="6" sign="-" format="ixt:num-dot-decimal">4,901</ix:nonFraction></td><td>)</td></tr>
        </table></body></html>'''


def test_inline_sign_scale_and_fiscal_year_survive_split_display_parentheses(tmp_path):
    source = tmp_path / "inline.html"
    source.write_text(inline_html())
    filing, html = load_filing(str(source), Settings(artifact_dir=tmp_path / "artifacts"))
    assert filing.metadata["period_end"] == "2025-06-30"
    rows, _ = parse_filing(html, filing)
    row = next(r for r in rows if r.label == "Other income (expense), net")
    assert [(f.period, f.value, f.cell, f.raw_value) for f in row.facts] == [("FY2025", -4901e6, 1, "4,901")]
    assert "( 4,901" in row.text and row.raw_cells[-1] == ")"


def test_cached_source_metadata_is_reparsed_instead_of_reusing_a_wrong_year(tmp_path, monkeypatch):
    calls = []
    def get(self, url):
        calls.append(url)
        return inline_html().encode()
    monkeypatch.setattr(SECClient, "get", get)
    source = "https://www.sec.gov/Archives/test.htm"
    settings = Settings(artifact_dir=tmp_path)
    load_filing(source, settings)
    index = tmp_path / "filings" / (digest(source) + ".json")
    saved = json.loads(index.read_text())
    saved["metadata"]["period_end"] = "2026-06-30"
    atomic_json(index, saved)
    filing, _ = load_filing(source, settings)
    assert filing.metadata["period_end"] == "2025-06-30"
    assert len(calls) == 1


def test_old_evidence_cache_is_bypassed_and_new_cache_is_reused(tmp_path, monkeypatch):
    source = Path("evaluation/fixtures/demo.html")
    settings = Settings(artifact_dir=tmp_path)
    atomic_json(tmp_path / "evidence" / (digest(source.read_bytes()) + "-ixbrl-table-v8.json"),
                {"rows": [], "statements": []})
    calls = []
    def tracked_parse(html, filing):
        calls.append(filing.content_hash)
        return parse_filing(html, filing)
    monkeypatch.setattr("financial_filing_agent.services.pipeline.parse_filing", tracked_parse)
    for _ in range(2):
        result = Pipeline(settings, ScriptedDecoder(), DemoRetriever()).run(
            "", str(source), ["FY2025", "FY2024"], formula_id="revenue_growth")
        assert result["final_status"] == "SUCCESS", result["warnings"]
        assert result["calculation_result"]["value"] == 10
    assert len(calls) == 1
