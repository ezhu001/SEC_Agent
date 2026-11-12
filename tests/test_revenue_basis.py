import pytest

from evaluation.review_double import review_response
from tests.test_metric_workflow import ConceptRetriever
from financial_filing_agent.config.settings import Settings
from financial_filing_agent.schemas.evidence import EvidenceRow, Fact
from financial_filing_agent.services.pipeline import Pipeline
from financial_filing_agent.tools.concept_validation import assess_concept, revenue_policy


PERIODS = ["FY2025", "FY2024"]


def source_row(ident, label, values, concept="RevenueFromContractWithCustomerExcludingAssessedTax"):
    return EvidenceRow(evidence_id=ident, filing_hash="filing", source="test", statement="operations",
        table=0, row=1, label=label, text=label, nearby_context="Consolidated Statements of Income in USD",
        facts=[Fact(period=p, value=value * 1_000_000, raw_value=str(value), unit="currency", currency="USD",
                    concept="us-gaap:" + concept, start=f"{year - 1}-02-01", end=f"{year}-01-31", cell=i)
               for i, (p, year, value) in enumerate(zip(PERIODS, [2025, 2024], values))])


def assess(row, rows):
    return assess_concept(row, "revenue", PERIODS, "filing", {r.evidence_id for r in rows},
                          revenue_basis_policy=revenue_policy(rows, PERIODS, "filing"))


@pytest.mark.parametrize("label", ["Revenue", "Revenues", "Total revenue", "Total revenues"])
def test_distinct_reported_total_takes_precedence_over_net_sales(label):
    sales = source_row("sales", "Net sales", [674538, 642637])
    total = source_row("total", label, [680985, 648125], "Revenues")
    assert assess(total, [sales, total])["status"] == "PASS"
    decision = assess(sales, [sales, total])
    assert decision["status"] == "FAIL"
    assert decision["revenue_basis"]["preferred_evidence_ids"] == ["total"]


@pytest.mark.parametrize("label", ["Net sales", "Total net sales"])
def test_net_sales_remains_supported_without_a_separate_reported_total(label):
    sales = source_row("sales", label, [416161, 391035])
    decision = assess(sales, [sales])
    assert decision["status"] == "PASS"
    assert decision["revenue_basis"]["basis"] == "net_sales"


@pytest.mark.parametrize("change", [
    {"dimensions": {"SegmentAxis": "Retail"}},
    {"unit": "percent", "currency": None},
    {"start": "2024-11-01"},
])
def test_ineligible_total_does_not_override_consolidated_annual_sales(change):
    sales = source_row("sales", "Net sales", [110, 100])
    total = source_row("total", "Total revenues", [120, 105], "Revenues")
    total.facts[0] = total.facts[0].model_copy(update=change)
    assert assess(sales, [sales, total])["status"] == "PASS"


def test_total_from_another_filing_does_not_change_the_basis():
    sales = source_row("sales", "Net sales", [110, 100])
    total = source_row("total", "Total revenues", [120, 105], "Revenues")
    total.filing_hash = "other-filing"
    assert assess(sales, [sales, total])["status"] == "PASS"


def test_identical_repeated_totals_are_supported_but_conflicts_do_not_choose_the_largest():
    total = source_row("total", "Total revenues", [120, 105], "Revenues")
    duplicate = total.model_copy(update={"evidence_id": "duplicate", "table": 1}, deep=True)
    assert assess(total, [total, duplicate])["status"] == "PASS"
    duplicate.facts[0].value += 1_000_000
    for row in (total, duplicate):
        decision = assess(row, [total, duplicate])
        assert decision["status"] == "FAIL"
        assert decision["revenue_basis"]["conflicting_periods"] == ["FY2025"]


class RevenueDecoder:
    version = {"name": "revenue-policy-test-double"}

    def __init__(self):
        self.calls = []

    def complete(self, role, system, payload, schema):
        assert role == "verifier"
        if payload["required_component"] == "revenue":
            assert payload["proposed_evidence"]["label"] == "Total revenues"
            assert payload["deterministic_concept_assessment"]["revenue_basis"]["basis"] == "reported_revenue"
        else:
            assert payload["proposed_evidence"]["label"] == "Operating income"
        self.calls.append({"role": role, "request": payload})
        return schema.model_validate(review_response(payload, {"verdict": "PASS", "error_type": "none", "confidence": 1.0,
                                      "reason": "Test source review"}))


class RevenueRetriever(ConceptRetriever):
    def rank(self, rows, component, periods, query):
        if component == "revenue":
            assert [r.label for r in rows] == ["Total revenues"]
        return super().rank(rows, component, periods, query)


def execute(tmp_path, rows, enabled, formula="revenue_growth"):
    contexts = "".join(f'<xbrli:context id="{p}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">123</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{f.start}</xbrli:startDate><xbrli:endDate>{f.end}</xbrli:endDate></xbrli:period></xbrli:context>'
                       for p, f in zip(PERIODS, rows[0].facts))
    contents = "".join('<tr><td>' + row.label + '</td>' + ''.join(
        f'<td><ix:nonFraction name="{f.concept}" contextRef="{f.period}" unitRef="usd" scale="6">{f.value / 1_000_000}</ix:nonFraction></td>' for f in row.facts) + '</tr>' for row in rows)
    source = tmp_path / "revenue.html"
    source.write_text('<html><body><ix:nonNumeric name="dei:EntityRegistrantName">Test Corporation</ix:nonNumeric>'
        '<ix:nonNumeric name="dei:EntityCentralIndexKey">123</ix:nonNumeric>'
        '<ix:nonNumeric name="dei:DocumentFiscalYearFocus">2025</ix:nonNumeric>'
        '<ix:nonNumeric name="dei:DocumentPeriodEndDate">2025-01-31</ix:nonNumeric>' + contexts +
        '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
        '<h2>CONSOLIDATED STATEMENTS OF OPERATIONS</h2><table>' + contents + '</table></body></html>')
    decoder = RevenueDecoder()
    result = Pipeline(Settings(artifact_dir=tmp_path, qwen_enabled=enabled), decoder, RevenueRetriever()).run(
        "", str(source), PERIODS, formula_id=formula)
    return result, decoder


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("formula,expected", [
    ("revenue_growth", (680985 / 648125 - 1) * 100),
    ("operating_margin_change", (29348 / 680985 - 27012 / 648125) * 100),
])
def test_walmart_revenue_definition_is_enforced_in_both_modes(tmp_path, monkeypatch, enabled, formula, expected):
    rows = [source_row("sales", "Net sales", [674538, 642637]),
            source_row("total", "Total revenues", [680985, 648125], "Revenues"),
            source_row("income", "Operating income", [29348, 27012], "OperatingIncomeLoss")]
    result, decoder = execute(tmp_path, rows, enabled, formula)
    assert result["final_status"] == "SUCCESS", result["errors"]
    assert result["final_response"]["evidence"]["revenue"]["label"] == "Total revenues"
    assert result["calculation_result"]["value"] == pytest.approx(expected, abs=1e-10)
    assert result["final_response"]["revenue_basis"]["basis"] == "reported_revenue"
    assert result["retrieval_diagnostics"]["revenue"][0]["revenue_basis"]["rejected"]
    assert not decoder.calls
    assert result["verification_results"]["revenue"][-1]["scope_assessment"]["status"] == "ESTABLISHED"


@pytest.mark.parametrize("enabled", [False, True])
def test_partial_total_cannot_be_replaced_by_complete_net_sales(tmp_path, monkeypatch, enabled):
    sales = source_row("sales", "Net sales", [110, 100])
    total = source_row("total", "Total revenues", [120, 105], "Revenues")
    total.facts = total.facts[:1]
    result, decoder = execute(tmp_path, [sales, total], enabled)
    assert result["final_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["calculation_result"] is None
    assert not decoder.calls
    assert not result["verification_results"]


def test_stale_net_sales_replacement_cannot_be_approved_by_an_agent(tmp_path):
    sales = source_row("sales", "Net sales", [110, 100])
    total = source_row("total", "Total revenues", [120, 105], "Revenues")
    decoder = RevenueDecoder()
    pipeline = Pipeline(Settings(artifact_dir=tmp_path, qwen_enabled=True), decoder, RevenueRetriever())
    pipeline.rows = lambda state: [sales, total]
    state = {"proposed_id": "sales", "active_component": "revenue", "required_periods": PERIODS,
             "filing_hash": "filing", "correction_attempts": 0, "guard_results": {},
             "verification_results": {}, "warnings": []}
    result = pipeline.verification(state)
    assert result["route"] == "correct"
    assert result["verification_results"]["revenue"][-1]["verdict"] == "FAIL"
    assert not decoder.calls
