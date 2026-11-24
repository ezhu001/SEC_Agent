import pytest
from pydantic import ValidationError

from financial_filing_agent.agents.corrector import correct, recovery_candidates
from financial_filing_agent.schemas.evidence import EvidenceRow, Fact, SourceText


PERIODS = ["FY2025", "FY2024"]


def asset_row(key, tag="us-gaap:AssetsCurrent", label="Total current assets"):
    return EvidenceRow(
        evidence_id=key, filing_hash="filing", source="example", statement="balance",
        table=1, row=1, label=label, text=label,
        statement_heading=SourceText(text="Consolidated Balance Sheets", locator="h", filing_hash="filing"),
        facts=[Fact(period=p, end=p[2:] + "-12-31", value=100, raw_value="100", cell=i,
                    instant=True, unit="currency", currency="USD", concept=tag, context_id=p,
                    entity_identifier="123", entity_scheme="http://www.sec.gov/CIK")
               for i, p in enumerate(PERIODS)])


def assess(rows):
    return recovery_candidates(rows, [r.evidence_id for r in rows], "current_assets",
                               PERIODS, "filing", {"cik": "123"})


def test_repeated_facts_are_one_replacement_and_different_assets_are_explained():
    total = asset_row("total", "us-gaap:Assets", "Total assets")
    candidates, excluded, selected = assess([total, asset_row("primary"), asset_row("note")])
    assert selected == "primary"
    assert candidates.keys() == {"primary", "note"}
    assert "us-gaap:Assets" in excluded["total"]


def test_different_values_cannot_shortcut_to_first_match():
    other = asset_row("other")
    other.facts[0].value += 1
    assert assess([asset_row("primary"), other])[2] is None


@pytest.mark.parametrize("change", ["custom", "mixed_period_tags", "restricted", "foreign", "missing_scope"])
def test_partial_or_unproven_identity_cannot_shortcut(change):
    row = asset_row("candidate")
    if change == "custom":
        for fact in row.facts:
            fact.concept = "issuer:AssetsCurrent"
    elif change == "mixed_period_tags":
        row.facts[-1].concept = None
    elif change == "restricted":
        row.facts[0].dimensions = {"axis": "member"}
    elif change == "foreign":
        row.facts[0].entity_identifier = "456"
    else:
        row.statement_heading = None
    candidates, excluded, selected = assess([row])
    assert selected is None
    assert row.evidence_id in (excluded if change in {"restricted", "foreign"} else candidates)


def test_no_current_assets_replacement():
    total = asset_row("total", "us-gaap:Assets", "Total assets")
    assert assess([total]) == ({}, {"total": "Different US-GAAP line item: us-gaap:Assets"}, None)


MISMATCH = {"assessment": "different_concept", "source_detail": "us-gaap:Assets"}
UNCLEAR = {"assessment": "unresolved_scope", "source_detail": "No issuer declaration"}


@pytest.mark.parametrize("reviews,valid", [
    ({"row-1": MISMATCH, "row-2": UNCLEAR}, True),
    ({"row-1": MISMATCH}, False),
    ({"invented": MISMATCH, "row-2": UNCLEAR}, False),
    ({"row-1": "Total assets", "row-2": UNCLEAR}, False),
    ({"row-1": {"assessment": "supported", "source_detail": "Debt"}, "row-2": UNCLEAR}, False),
])
def test_model_declines_identify_each_supplied_candidate(reviews, valid):
    class Decoder:
        def complete(self, role, system, payload, schema):
            return schema.model_validate({"decision": "NO_VALID_EVIDENCE", "evidence_id": None,
                                          "reason": "No supported replacement", "confidence": 0.8,
                                          "candidate_reviews": reviews})
    payload = {"available_candidates": [{"evidence_id": "row-1"}, {"evidence_id": "row-2"}]}
    if valid:
        assert correct(Decoder(), payload).model_dump()["candidate_reviews"] == reviews
    else:
        with pytest.raises(ValidationError):
            correct(Decoder(), payload)


def test_model_cannot_replace_with_row_it_marks_as_different_concept():
    class Decoder:
        def complete(self, role, system, payload, schema):
            return schema.model_validate({"decision": "REPLACE", "evidence_id": "row-1", "confidence": 0.9,
                                          "reason": "Use this row", "candidate_reviews": {"row-1": MISMATCH}})
    with pytest.raises(ValidationError, match="did not support"):
        correct(Decoder(), {"available_candidates": [{"evidence_id": "row-1"}]})


@pytest.mark.parametrize("category", ["wrong_statement", "wrong_period", "wrong_unit", "unresolved_scope"])
def test_recovery_cannot_blame_checks_already_established(category):
    class Decoder:
        def complete(self, role, system, payload, schema):
            return schema.model_validate({"decision": "NO_VALID_EVIDENCE", "evidence_id": None,
                "confidence": 0.8, "reason": "No supported asset", "candidate_reviews": {"debt": {
                    "assessment": category, "source_detail": "Current portion of debt, balance sheet"}}})
    with pytest.raises(ValidationError):
        correct(Decoder(), {"available_candidates": [{"evidence_id": "debt", "assessment": {
            "concept_status": "UNCERTAIN", "scope_status": "ESTABLISHED"}}]})

@pytest.mark.parametrize("heading,tag,label,excluded", [
    ("Current liabilities", "issuer:FinanceLeasesCurrent", "Current portion of debt", True),
    ("Current liabilities", "issuer:OtherCurrentLiabilities", "Accrued liabilities", True),
    ("Current liabilities", "issuer:Custom", "Assets held for sale", False),
    ("Current assets", "issuer:Custom", "Debt securities", False),
    ("Current liabilities", "issuer:Custom", "Debt securities", False),
    ("Current liabilities", "us-gaap:AssetsCurrent", "Total current assets", False),
])
def test_custom_tag_needs_both_liability_heading_and_label_to_exclude(heading, tag, label, excluded):
    row = asset_row("row", tag, label)
    row.row_group_heading = SourceText(text=heading, locator="table:1:row:0", filing_hash="filing")
    _, reasons, _ = assess([row])
    assert ("row" in reasons) == excluded
    if excluded:
        assert heading in reasons["row"] and label in reasons["row"]
