from typing import TypedDict


class RunState(TypedDict, total=False):
    input_inventory: list[dict]
    requested_filing_source: str
    request_id: str
    user_question: str
    filing_source: str
    filing_metadata: dict
    filing_hash: str
    parsed_statements: list[dict]
    evidence_artifact_reference: str
    task_plan: dict
    required_components: list[str]
    required_periods: list[str]
    formula_id: str
    retrieval_results: dict
    top_k_candidates: dict
    retrieval_diagnostics: dict
    evidence_sufficiency: dict
    verification_results: dict
    correction_results: dict
    accepted_evidence: dict
    guard_results: dict
    calculation_result: dict | None
    final_status: str
    final_response: dict
    warnings: list[str]
    errors: list[dict]
    audit_events: list[dict]
    timings: dict
    decoder_call_count: int
    expanded_search_count: int
    correction_count: int
    config_version: str
    config_hash: str
    model_versions: dict
    active_component: str
    component_index: int
    candidate_scope: str
    proposed_id: str | None
    correction_attempts: int
    component_expansions: int
    route: str
