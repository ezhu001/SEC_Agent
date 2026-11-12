from pathlib import Path

import pytest

from financial_filing_agent.config.settings import Settings
from financial_filing_agent.tools.filing_loader import load_filing
from financial_filing_agent.tools.filing_parser import parse_filing
from financial_filing_agent.tools.scope_validation import assess_scope


PERIODS = ["FY2025"]


def filing_html(heading="INCOME STATEMENTS", entity="123", declaration=True):
    scope = "<p>The consolidated financial statements include the accounts of Example Corporation and its subsidiaries.</p>" if declaration else ""
    fact = '<ix:nonFraction name="us-gaap:Revenues" contextRef="current" unitRef="usd" scale="6">110</ix:nonFraction>'
    return f'''<html><body><ix:nonNumeric name="dei:EntityRegistrantName">Example Corporation</ix:nonNumeric>
        <ix:nonNumeric name="dei:EntityCentralIndexKey">123</ix:nonNumeric>
        <ix:nonNumeric name="dei:DocumentFiscalYearFocus">2025</ix:nonNumeric>
        <ix:nonNumeric name="dei:DocumentPeriodEndDate">2025-12-31</ix:nonNumeric>
        <xbrli:context id="current"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{entity}</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
        <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
        {scope}<h2>{heading}</h2><table><tr><td>Total revenue</td><td>{fact}</td></tr>
        <tr><td>Operating income</td><td>20</td></tr></table>
        <h2>Notes to Financial Statements</h2><p>{'Accounting policies. ' * 60}</p>
        <table><tr><td>Total</td><td></td></tr><tr><td>Revenue</td><td>{fact}</td></tr>
        <tr><td>Operating income</td><td>20</td></tr></table></body></html>'''


def parsed(tmp_path, **options):
    path = tmp_path / "filing.html"
    path.write_text(filing_html(**options))
    filing, html = load_filing(str(path), Settings(artifact_dir=tmp_path / "artifacts"))
    return filing, parse_filing(html, filing)[0]


def test_primary_statement_and_repeated_note_total_have_source_backed_scope(tmp_path):
    filing, rows = parsed(tmp_path)
    primary = next(r for r in rows if r.label == "Total revenue")
    repeated = next(r for r in rows if r.label == "Revenue")
    assert primary.statement_heading.text == "INCOME STATEMENTS"
    assert primary.statement_heading.locator.startswith("element:")
    assert repeated.row_group_heading.text == "Total"
    assert primary.facts[0].entity_identifier == "123"
    assert assess_scope(primary, rows, PERIODS, filing.metadata)["status"] == "ESTABLISHED"
    decision = assess_scope(repeated, rows, PERIODS, filing.metadata)
    assert decision["status"] == "ESTABLISHED"
    assert decision["related_evidence_ids"] == [primary.evidence_id]


def test_heading_word_split_across_inline_spans_is_reconstructed_from_dom_text(tmp_path):
    filing, rows = parsed(tmp_path, heading="<span>INC</span><span>OME STATEMENTS</span>")
    primary = next(r for r in rows if r.label == "Total revenue")
    assert primary.statement_heading.text == "INCOME STATEMENTS"
    assert assess_scope(primary, rows, PERIODS, filing.metadata)["status"] == "ESTABLISHED"


def test_a_neighbouring_financial_table_does_not_inherit_the_primary_heading(tmp_path):
    html = filing_html().replace('<h2>Notes to Financial Statements</h2>', '')
    html = html.replace('<p>' + 'Accounting policies. ' * 60 + '</p>', '')
    # This second table is not an exact repeated fact and has no own statement heading.
    last = html.rfind('>110</ix:nonFraction>')
    html = html[:last] + html[last:].replace('>110</ix:nonFraction>', '>111</ix:nonFraction>', 1)
    path = tmp_path / "neighbour.html"
    path.write_text(html)
    filing, raw = load_filing(str(path), Settings(artifact_dir=tmp_path / "artifacts"))
    rows, _ = parse_filing(raw, filing)
    repeated = next(r for r in rows if r.label == "Revenue")
    assert repeated.statement_heading is None
    assert assess_scope(repeated, rows, PERIODS, filing.metadata)["status"] == "UNRESOLVED"


def test_empty_dimensions_and_matching_entity_do_not_alone_establish_scope(tmp_path):
    filing, rows = parsed(tmp_path, heading="Financial data", declaration=False)
    row = next(r for r in rows if r.label == "Total revenue")
    assert row.facts[0].dimensions == {}
    assert assess_scope(row, rows, PERIODS, filing.metadata)["status"] == "UNRESOLVED"


@pytest.mark.parametrize("change", ["entity", "dimensions", "parent_only", "parent_company", "subsidiary_group"])
def test_restricted_scope_cannot_be_overridden_by_consolidated_document_text(tmp_path, change):
    filing, rows = parsed(tmp_path)
    row = next(r for r in rows if r.label == "Total revenue")
    if change == "entity":
        row.facts[0].entity_identifier = "999"
    elif change == "dimensions":
        row.facts[0].dimensions = {"SegmentAxis": "Retail"}
    else:
        row.row_group_heading = row.statement_heading.model_copy(update={"text": {
            "parent_only": "Parent-only", "parent_company": "Parent Company Financial Statements",
            "subsidiary_group": "Subsidiaries"}[change]})
    assert assess_scope(row, rows, PERIODS, filing.metadata)["status"] == "RESTRICTED"


@pytest.mark.parametrize("change", ["concept", "value", "context_id", "foreign_filing"])
def test_numeric_coincidence_or_foreign_row_does_not_create_a_primary_link(tmp_path, change):
    filing, rows = parsed(tmp_path)
    primary = next(r for r in rows if r.label == "Total revenue")
    repeated = next(r for r in rows if r.label == "Revenue")
    if change == "foreign_filing":
        primary.filing_hash = "foreign"
    elif change == "value":
        repeated.facts[0].value += 1
    else:
        setattr(repeated.facts[0], change, "different")
    assert assess_scope(repeated, rows, PERIODS, filing.metadata)["status"] == "UNRESOLVED"


def test_foreign_declaration_is_not_a_scope_certificate(tmp_path):
    filing, rows = parsed(tmp_path)
    primary = next(r for r in rows if r.label == "Total revenue")
    primary.scope_declarations = [s.model_copy(update={"filing_hash": "foreign"}) for s in primary.scope_declarations]
    assert assess_scope(primary, [primary], PERIODS, filing.metadata)["status"] == "UNRESOLVED"


def test_missing_entity_information_is_unresolved_not_a_contradiction(tmp_path):
    filing, rows = parsed(tmp_path)
    primary = next(r for r in rows if r.label == "Total revenue")
    primary.facts[0].entity_identifier = None
    assert assess_scope(primary, [primary], PERIODS, filing.metadata)["status"] == "UNRESOLVED"


def test_foreign_entity_is_a_source_scope_failure_before_any_model_call(tmp_path):
    from evaluation.doubles import DemoRetriever, ScriptedDecoder
    from financial_filing_agent.services.pipeline import Pipeline
    filing, rows = parsed(tmp_path, entity="999")
    primary = next(r for r in rows if r.label == "Total revenue")
    decoder = ScriptedDecoder()
    pipeline = Pipeline(Settings(artifact_dir=tmp_path), decoder, DemoRetriever())
    pipeline.rows = lambda state: rows
    result = pipeline.verification({"proposed_id": primary.evidence_id, "active_component": "revenue",
        "required_periods": PERIODS, "filing_hash": filing.content_hash, "filing_metadata": filing.metadata,
        "correction_attempts": 0, "warnings": [], "guard_results": {}, "verification_results": {}})
    review = result["verification_results"]["revenue"][-1]
    assert review["verdict"] == "FAIL" and review["error_type"] == "wrong_context"
    assert review["scope_assessment"]["status"] == "RESTRICTED"
    assert not decoder.calls


def test_uncertain_selection_is_retried_only_when_scope_evidence_changes(tmp_path):
    from evaluation.doubles import DemoRetriever, ScriptedDecoder
    from financial_filing_agent.tools.scope_validation import scope_fingerprint
    from financial_filing_agent.services.pipeline import Pipeline
    filing, rows = parsed(tmp_path)
    primary = next(r for r in rows if r.label == "Total revenue")
    unknown = primary.model_copy(update={"statement_heading": None, "scope_declarations": []}, deep=True)
    original = assess_scope(unknown, [unknown], PERIODS, filing.metadata)
    pipeline = Pipeline(Settings(artifact_dir=tmp_path), ScriptedDecoder(), DemoRetriever())
    pipeline.rows = lambda state: [unknown]
    state = {"required_periods": PERIODS, "filing_metadata": filing.metadata,
        "verification_results": {"revenue": [{"verdict": "UNCERTAIN", "evidence_id": primary.evidence_id,
            "scope_fingerprint": scope_fingerprint(unknown, original, filing.metadata)}]}}
    assert pipeline.review_rejections(state, "revenue") == {primary.evidence_id}
    pipeline.rows = lambda state: [primary]
    assert not pipeline.review_rejections(state, "revenue")
    state["verification_results"]["revenue"][0]["verdict"] = "FAIL"
    assert pipeline.review_rejections(state, "revenue") == {primary.evidence_id}
