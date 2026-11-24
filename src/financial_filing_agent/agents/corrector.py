import re
from typing import Literal

from pydantic import create_model, model_validator

from ..config.financial_concepts import CONCEPTS
from ..config.prompts import CORRECTOR
from ..models.local_decoder import DecoderError
from ..schemas.evidence import Record
from ..schemas.results import Correction, RecoveryObservation
from ..tools.concept_validation import assess_concept, revenue_policy
from ..tools.numeric_parser import normalize
from ..tools.scope_validation import assess_scope, fact_identity


def recovery_candidates(rows, ranked_ids, component, periods, filing_hash, metadata):
    by_id = {row.evidence_id: row for row in rows}
    policy = revenue_policy(rows, periods, filing_hash) if component == "revenue" else None
    _, aliases, concepts = CONCEPTS[component]
    expected = {"us-gaap:" + concept for concept in concepts}
    candidates, excluded, proven = {}, {}, {}
    for evidence_id in ranked_ids:
        row = by_id[evidence_id]
        concept = assess_concept(row, component, periods, filing_hash, by_id, revenue_basis_policy=policy)
        if concept["status"] == "FAIL":
            excluded[evidence_id] = concept["reason"]
            continue
        tags = {f.concept for f in row.facts if f.period in periods}
        # For current assets, differently tagged US-GAAP line items with unrelated
        # labels cannot supply the reported subtotal. Keep custom/untagged rows for review.
        if (component == "current_assets" and tags.isdisjoint(expected)
                and all(tag and tag.startswith("us-gaap:") for tag in tags)
                and normalize(row.label) not in aliases):
            excluded[evidence_id] = "Different US-GAAP line item: " + ", ".join(sorted(tags))
            continue
        group = row.row_group_heading
        if (component == "current_assets" and tags.isdisjoint(expected) and group and group.filing_hash == filing_hash
                and normalize(group.text) in {"current liabilities", "noncurrent liabilities", "long term liabilities", "liabilities"}
                and re.search(r"\b(liabilities|borrowings|portion of (?:long term )?debt|debt and finance leases)\b",
                              normalize(row.label))):
            excluded[evidence_id] = f"Different concept: {row.label} appears under {group.text} ({group.locator})"
            continue
        scope = assess_scope(row, rows, periods, metadata)
        if scope["status"] == "RESTRICTED":
            excluded[evidence_id] = scope["reason"]
            continue
        candidates[evidence_id] = {"concept_status": concept["status"], "concept_reason": concept["reason"],
                                   "scope_status": scope["status"], "scope_reason": scope["reason"]}
        if concept["status"] == "PASS" and scope["status"] == "ESTABLISHED" and tags <= expected:
            identity = fact_identity(row, periods)
            if identity:
                proven.setdefault(tuple(identity), evidence_id)
    unique = next(iter(proven.values())) if len(proven) == 1 else None
    return candidates, excluded, unique


class ReviewedCorrection(Correction):
    candidate_reviews: Record

    @model_validator(mode="after")
    def consistent_reviews(self):
        supported = {key for key, review in self.candidate_reviews if review.assessment == "supported"}
        if self.decision == "REPLACE" and self.evidence_id not in supported:
            raise ValueError("Corrector selected a replacement its own candidate review did not support")
        if self.decision != "REPLACE" and supported:
            raise ValueError("A decline cannot mark candidates supported; identify their actual mismatch or ambiguity")
        return self


def correct(decoder, payload):
    candidates = payload["available_candidates"]
    fields = {}
    for index, candidate in enumerate(candidates):
        assessment = candidate.get("assessment", {})
        choices = ["supported", "ambiguous_evidence"]
        if assessment.get("concept_status") != "PASS":
            choices.append("different_concept")
        if assessment.get("scope_status") != "ESTABLISHED":
            choices.append("unresolved_scope")
        observation = create_model(f"Observation{index}", __base__=RecoveryObservation,
                                   assessment=(Literal[tuple(choices)], ...))
        fields[candidate["evidence_id"]] = (observation, ...)
    reviews = create_model("CandidateReviews", __base__=Record, **fields)
    schema = create_model("CandidateCorrection", __base__=ReviewedCorrection, candidate_reviews=(reviews, ...))
    result = decoder.complete("corrector", CORRECTOR, payload, schema)
    if result.decision == "REPLACE" and result.evidence_id not in {c["evidence_id"] for c in candidates}:
        raise DecoderError("Corrector selected an evidence ID outside the supplied candidate set")
    if result.decision == "EXPAND_SEARCH" and not payload.get("expansion_allowed", False):
        raise DecoderError("Corrector requested an expansion forbidden by the explicit remaining budget")
    if result.decision != "REPLACE" and re.search(r"accounting[ _-]*identity|certificate|reconcil", result.reason, re.I):
        raise DecoderError("Recovery cannot require an optional Python accounting certificate or expand search to obtain one")
    return result
