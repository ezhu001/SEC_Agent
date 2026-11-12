import copy
import json
import time
import uuid
import platform
import importlib.metadata
from datetime import datetime, timezone
from pathlib import Path

from ..agents.planner import plan_task
from ..agents.verifier import verify
from ..agents.verification_contract import build_contract
from ..agents.corrector import correct
from ..config.financial_concepts import CONCEPTS
from ..config.financial_concepts import definition
from ..config.formulas import FORMULAS
from ..config.formulas import registered_plan
from ..config.settings import Settings
from ..graph.workflow import build_graph
from ..models.finbert import get_finbert
from ..models.local_decoder import OllamaDecoder
from ..retrieval.hybrid_retriever import HybridRetriever
from ..retrieval.sufficiency import assess
from ..schemas.evidence import Filing, EvidenceRow
from ..schemas.task import TaskPlan
from ..tools.filing_loader import load_filing
from ..tools.filing_parser import parse_filing
from ..tools.validation import eligibility, guard, EvidenceError
from ..tools.calculator import calculate
from ..tools.input_inventory import inventory, missing_periods
from ..tools.supporting_filing import find_complete_filing
from ..tools.concept_validation import assess_concept, gross_profit_identity, revenue_policy, assess_revenue_basis
from ..tools.scope_validation import assess_scope, scope_fingerprint
from .audit import Audit
from .cache import atomic_json
from .progress import LABELS, summary


class Pipeline:
    """One instance per run. Heavy encoder is process-cached; run context is isolated."""
    def __init__(self, settings=None, decoder=None, retriever=None):
        self.settings = settings or Settings()
        self.decoder = decoder or OllamaDecoder(self.settings)
        s = self.settings
        self.retriever = retriever or HybridRetriever(lambda: get_finbert(s.finbert_model, s.finbert_revision,
                    s.finbert_device, s.token_limit, s.batch_size), s)
        self.requested_periods = None
        self.on_progress = None

    def notify(self, phase, node, state, seconds=0):
        if self.on_progress:
            event = {"phase": phase, "node": node, "label": LABELS[node],
                     "component": state.get("active_component"), "seconds": seconds,
                     "status": state.get("final_status", ""),
                     "detail": summary(node, state) if phase == "completed" else ""}
            try:
                self.on_progress(event)
            except Exception:
                # Progress is observational; a display failure cannot authorize
                # evidence or alter the calculation/control flow.
                import logging
                logging.getLogger(__name__).exception("Progress callback failed")

    def audit_failure(self, state, exc):
        errors = state["errors"]
        if not any(e.get("node") == "audit_persistence" for e in errors):
            errors = errors + [{"node": "audit_persistence", "type": type(exc).__name__, "message": str(exc)}]
        return {"final_status": "ERROR", "calculation_result": None, "errors": errors}

    def rows(self, state):
        return [EvidenceRow.model_validate(r) for r in json.loads(Path(state["evidence_artifact_reference"]).read_text(encoding="utf-8"))]

    def recover_route(self, state):
        if state["correction_attempts"] < self.settings.correction_budget:
            return {"route": "correct"}
        return {"final_status": "INSUFFICIENT_EVIDENCE", "warnings": state["warnings"] + ["Recovery budget exhausted for " + state["active_component"]]}

    def validate_request(self, s):
        if not s["filing_source"].strip() or (not s["user_question"].strip() and not self.selected_formula):
            return {"final_status": "NEEDS_INPUT", "warnings": ["Provide a question and filing source."]}
        return {"route": "load_filing"}

    def load(self, s):
        filing, _ = load_filing(s["filing_source"], self.settings)
        self.filing = filing
        return {"filing_metadata": filing.metadata, "filing_source": filing.source, "filing_hash": filing.content_hash,
                "route": "plan_task"}

    def plan(self, s):
        if not self.settings.qwen_enabled and not self.selected_formula:
            return {"task_plan": {"status": "NEEDS_INPUT", "notes": "Qwen agents are disabled. Select a registered metric and explicit fiscal periods."},
                    "final_status": "NEEDS_INPUT", "warnings": s["warnings"] + ["Qwen disabled: choose a metric from the menu and specify fiscal years."]}
        plan = (registered_plan(self.selected_formula, self.requested_periods) if self.selected_formula else
                plan_task(self.decoder, s["user_question"], s["filing_metadata"], self.requested_periods))
        update = {"task_plan": plan.model_dump(mode="json"), "warnings": s["warnings"] + ([plan.notes] if plan.notes else [])}
        if plan.status != "READY":
            return {**update, "final_status": plan.status}
        return {**update, "required_components": plan.required_components, "required_periods": plan.required_periods,
                "formula_id": plan.formula_id, "route": "build_evidence"}

    def evidence(self, s):
        cache = self.settings.artifact_dir / "evidence" / (s["filing_hash"] + "-" + self.settings.parser_version + ".json")
        started = time.perf_counter()
        if cache.exists():
            saved = json.loads(cache.read_text(encoding="utf-8"))
            rows = [EvidenceRow.model_validate(r) for r in saved["rows"]]
            statements = saved["statements"]
        else:
            rows, statements = parse_filing(Path(self.filing.local_path).read_text(encoding="utf-8"), self.filing)
            atomic_json(cache, {"rows": [r.model_dump(mode="json") for r in rows], "statements": statements})
        artifact = self.audit.directory / "evidence.json"
        # Rebind provenance to this run's source (same bytes may have multiple paths).
        for row in rows:
            row.source = s["filing_source"]
        atomic_json(artifact, [r.model_dump(mode="json") for r in rows])
        return {"evidence_artifact_reference": str(artifact.resolve()), "parsed_statements": statements,
                "component_index": 0, "timings": {**s["timings"], "filing_parse_seconds": time.perf_counter() - started},
                "route": "check_inputs"}

    def check_inputs(self, s):
        plan = TaskPlan.model_validate(s["task_plan"])
        cells = inventory(self.rows(s), plan)
        missing = missing_periods(cells)
        if not missing:
            return {"input_inventory": cells, "route": "retrieve_component"}
        selected, attempts = find_complete_filing(self.filing, plan, self.settings,
                            self.supplementary_sources, self.use_cached_filings)
        if selected:
            previous = s["filing_source"]
            self.filing, rows, statements = selected
            artifact = self.audit.directory / "evidence-supporting.json"
            atomic_json(artifact, [r.model_dump(mode="json") for r in rows])
            return {"filing_source": self.filing.source, "filing_hash": self.filing.content_hash,
                    "evidence_artifact_reference": str(artifact.resolve()),
                    "filing_metadata": self.filing.metadata, "parsed_statements": statements,
                    "input_inventory": inventory(rows, plan), "route": "retrieve_component",
                    "warnings": s["warnings"] + [f"Requested years were unavailable in {previous}. Using the complete same-company supporting filing: {self.filing.source}. No facts were invented or mixed across filings."],
                    "audit_events": s["audit_events"] + [self.audit.event("supporting_filing_search", 0, {"attempts": attempts, "selected_source": self.filing.source})]}
        details = "; ".join(f"{c['component']} / {c['period']}" for c in missing)
        return {"input_inventory": cells, "final_status": "INSUFFICIENT_EVIDENCE",
                "audit_events": s["audit_events"] + [self.audit.event("supporting_filing_search", 0, {"attempts": attempts, "selected_source": None})],
                "warnings": s["warnings"] + ["Missing required statement-period inputs: " + details +
                    ". Supply a same-company filing covering these years, or select the years actually reported. No model verification or calculation can supply missing balances."]}

    def rank_eligible(self, s, component, rows):
        known_ids = {row.evidence_id for row in rows}
        eligible, rejected = [], []
        for row in rows:
            result = eligibility(row, component, s["required_periods"], s["filing_hash"], known_ids)
            if result["passed"]:
                eligible.append(row)
            else:
                rejected.append(result)
        ranking_rows, basis_diagnostics = eligible, {}
        if component == "revenue":
            policy = revenue_policy(rows, s["required_periods"], s["filing_hash"])
            assessments = {r.evidence_id: assess_revenue_basis(r, policy) for r in eligible}
            ranking_rows = [r for r in eligible if assessments[r.evidence_id]["status"] == "PASS"]
            basis_diagnostics = {"revenue_basis": {**policy,
                "rejected": [{"evidence_id": r.evidence_id, **assessments[r.evidence_id]}
                             for r in eligible if assessments[r.evidence_id]["status"] != "PASS"]}}
        if ranking_rows:
            ranked, diagnostics = self.retriever.rank(ranking_rows, component, s["required_periods"],
                                                      s["task_plan"]["retrieval_queries"][component])
        else:
            ranked, diagnostics = [], {"candidate_count": 0}
        return ranked, {**diagnostics, **basis_diagnostics, "eligibility": {"examined_count": len(rows),
                       "eligible_count": len(eligible), "rejected": rejected}}

    def retrieve(self, s):
        component = s["required_components"][s["component_index"]]
        ranked, diagnostics = self.rank_eligible(s, component, self.rows(s))
        # Initial scope is top-k of eligible rows; expansion retains the same source constraints.
        top = ranked[:self.settings.top_k]
        warnings = s["warnings"]
        if not ranked:
            failed = sorted({key for record in diagnostics["eligibility"]["rejected"]
                             for key, passed in record["checks"].items() if not passed})
            reason = (f"No structurally eligible evidence for {component}. Failed checks: " + ", ".join(failed)
                      if not diagnostics["eligibility"]["eligible_count"] else f"No ranked evidence for {component} in the searched scope.")
            if diagnostics.get("revenue_basis", {}).get("rejected"):
                reason += " " + diagnostics["revenue_basis"]["rejected"][0]["reason"]
            warnings = warnings + [reason]
        return {"active_component": component, "retrieval_results": {**s["retrieval_results"], component: ranked},
                "top_k_candidates": {**s["top_k_candidates"], component: top},
                "retrieval_diagnostics": {**s["retrieval_diagnostics"], component: [diagnostics]},
                "candidate_scope": "TOP_K", "proposed_id": top[0]["evidence_id"] if top else None,
                "correction_attempts": 0, "component_expansions": 0, "route": "assess_sufficiency",
                "warnings": warnings, **({"final_status": "INSUFFICIENT_EVIDENCE"} if not ranked else {})}

    def sufficiency(self, s):
        c = s["active_component"]
        pool = s["top_k_candidates"][c] if s["candidate_scope"] == "TOP_K" else s["retrieval_results"][c]
        failed_ids = {r["evidence_id"] for r in s["guard_results"].get(c, []) if not r["passed"]}
        failed_ids |= self.review_rejections(s, c)
        pool = [r for r in pool if r["evidence_id"] not in failed_ids]
        # Propose a structurally eligible row, never borrow period availability
        # from an unrelated row or financial statement in the expanded pool.
        eligible = [r for r in pool if all(r["signals"][key] for key in ("statement", "periods", "numeric"))]
        if eligible:
            pool = eligible
        result = assess(pool)
        update = {"evidence_sufficiency": {**s["evidence_sufficiency"], c: s["evidence_sufficiency"].get(c, []) + [result]},
                  "proposed_id": pool[0]["evidence_id"] if pool else None}
        if result["status"] == "SUFFICIENT":
            return {**update, "route": "verify"}
        if s["component_expansions"] < self.settings.expansion_budget:
            return {**update, "route": "expand_search"}
        if result["status"] == "UNCERTAIN":
            # The verifier resolves ambiguous semantics, never a missing numeric period.
            return {**update, "route": "verify"}
        return {**update, "final_status": "INSUFFICIENT_EVIDENCE", "warnings": s["warnings"] + [result["reason"]]}

    def expand(self, s):
        if s["component_expansions"] >= self.settings.expansion_budget:
            return {"final_status": "INSUFFICIENT_EVIDENCE", "warnings": s["warnings"] + ["Search expansion exhausted"]}
        c = s["active_component"]
        ranked, diag = self.rank_eligible(s, c, self.rows(s))
        return {"retrieval_results": {**s["retrieval_results"], c: ranked}, "candidate_scope": "ALL_PARSED_STATEMENTS",
                "retrieval_diagnostics": {**s["retrieval_diagnostics"], c: s["retrieval_diagnostics"][c] + [diag]},
                "proposed_id": ranked[0]["evidence_id"] if ranked else None,
                "component_expansions": s["component_expansions"] + 1,
                "expanded_search_count": s["expanded_search_count"] + 1, "route": "assess_sufficiency"}

    def model_payload(self, s):
        c = s["active_component"]
        components = FORMULAS[s["formula_id"]].components
        return {"original_question": s["user_question"], "required_component": c, "filing_hash": s["filing_hash"],
            "formula_id": s["formula_id"],
            "component_formula_role": {"component": c,
                "role": "growth_input" if len(components) == 1 else "numerator" if c == components[0] else "denominator",
                "other_components_reviewed_separately": [name for name in components if name != c]},
            "expected_statement": CONCEPTS[c][0], "required_periods": s["required_periods"],
            "semantic_query": s["task_plan"]["retrieval_queries"][c],
            "concept_definition": definition(c),
            "formula_role": FORMULAS[s["formula_id"]].description,
            "filing_metadata": s["filing_metadata"]}

    def decoder_evidence(self, row, periods):
        # Full source rows remain in the evidence artifact. Avoid repeating the
        # whole surrounding table for every alternative in the decoder context.
        record = {"evidence_id": row.evidence_id, "label": row.label, "statement": row.statement,
                  "filing_hash": row.filing_hash, "table": row.table, "row": row.row,
                  "text": row.text, "nearby_context": row.nearby_context[-600:],
                  "statement_heading": row.statement_heading.model_dump() if row.statement_heading else None,
                  "row_group_heading": row.row_group_heading.model_dump() if row.row_group_heading else None}
        record["facts"] = [f.model_dump(mode="json", exclude={"raw_value"})
                           for f in row.facts if f.period in periods]
        return record

    def review_rejections(self, s, component):
        rows = {r.evidence_id: r for r in self.rows(s)}
        rejected = set()
        for review in s["verification_results"].get(component, []):
            if review["verdict"] == "FAIL":
                rejected.add(review["evidence_id"])
            elif review["verdict"] == "UNCERTAIN":
                row = rows.get(review["evidence_id"])
                metadata = s.get("filing_metadata", {})
                current = assess_scope(row, list(rows.values()), s["required_periods"], metadata) if row else {}
                if not row or not review.get("scope_fingerprint") or review["scope_fingerprint"] == scope_fingerprint(row, current, metadata):
                    rejected.add(review["evidence_id"])
        return rejected

    def verification(self, s):
        rows = {r.evidence_id: r for r in self.rows(s)}
        proposed = rows.get(s["proposed_id"])
        if proposed is None:
            return {"final_status": "INSUFFICIENT_EVIDENCE", "warnings": s["warnings"] + ["No source proposal to verify"]}
        c = s["active_component"]
        mechanical = eligibility(proposed, c, s["required_periods"], s["filing_hash"], set(rows))
        if not mechanical["passed"]:
            failed = ", ".join(key for key, passed in mechanical["checks"].items() if not passed)
            recovery = self.recover_route(s)
            warnings = recovery.pop("warnings", s["warnings"])
            return {**recovery, "guard_results": {**s["guard_results"],
                    c: s["guard_results"].get(c, []) + [mechanical]},
                    "warnings": warnings + [f"Evidence {proposed.evidence_id} failed before verification: {failed}."]}
        policy = revenue_policy(list(rows.values()), s["required_periods"], s["filing_hash"]) if c == "revenue" else None
        concept = assess_concept(proposed, c, s["required_periods"], s["filing_hash"], set(rows), revenue_basis_policy=policy)
        scope = assess_scope(proposed, list(rows.values()), s["required_periods"], s.get("filing_metadata", {}))
        identity = (gross_profit_identity(proposed, list(rows.values()), s["required_periods"])
                    if c == "gross_profit" and concept["status"] == "PASS" else {"status": "NOT_APPLICABLE"})
        identity["required"] = False
        # A verified source accounting identity is a stronger concept certificate
        # than a decoder's label-only reinterpretation. Record this explicitly.
        if concept["status"] == "FAIL" or scope["status"] == "RESTRICTED" or identity["status"] == "MISMATCH" or not self.settings.qwen_enabled or (identity["status"] == "PASS" and scope["status"] == "ESTABLISHED"):
            passed = concept["status"] == "PASS" and scope["status"] == "ESTABLISHED" and identity["status"] != "MISMATCH"
            if scope["status"] == "RESTRICTED":
                reason = scope["reason"]
            elif concept["status"] == "FAIL":
                reason = concept["reason"]
            elif identity["status"] == "PASS":
                reason = "Python source accounting identity confirms a monetary gross-profit subtotal; no decoder arithmetic or label-only veto was used."
            elif identity["status"] == "MISMATCH":
                reason = "Python accounting identity mismatch: reported amount differs from same-table revenue minus cost of sales."
            else:
                reason = scope["reason"] if scope["status"] != "ESTABLISHED" else concept["reason"]
            record = {"evidence_id": proposed.evidence_id, "verdict": "PASS" if passed else "FAIL" if concept["status"] == "FAIL" or scope["status"] == "RESTRICTED" else "UNCERTAIN",
                "error_type": "none" if passed else "wrong_context" if scope["status"] == "RESTRICTED" else "wrong_line_item" if concept["status"] == "FAIL" else "insufficient_evidence", "confidence": None,
                "reason": reason,
                "method": "deterministic_scope_rules" if scope["status"] == "RESTRICTED" else "deterministic_accounting_identity" if identity["status"] == "PASS" else "deterministic_concept_rules",
                "concept_assessment": concept, "accounting_identity": identity}
        else:
            payload = {**self.model_payload(s), "proposed_evidence": self.decoder_evidence(proposed, s["required_periods"]),
                       "deterministic_concept_assessment": concept, "scope_assessment": scope}
            result = verify(self.decoder, payload)
            contract = build_contract(payload)
            record = {"evidence_id": proposed.evidence_id, **result.model_dump(mode="json"),
                      "method": "qwen" if contract["open_checks"] else "deterministic_source_scope",
                      "concept_assessment": concept, "accounting_identity": identity,
                      "verification_contract": contract, "model_reason": result.reason}
            if result.verdict == "PASS":
                # Keep the exact model prose for inspection, but present a
                # stable description of what its validated output authorizes.
                record["reason"] = "; ".join(f"{check.check}={check.status}: {check.evidence_quote[:100]}" for check in result.checks) + ". Python-resolved checks remain fixed."
        record["scope_assessment"] = scope
        record["scope_fingerprint"] = scope_fingerprint(proposed, scope, s.get("filing_metadata", {}))
        update = {"verification_results": {**s["verification_results"], c: s["verification_results"].get(c, []) + [record]}}
        return {**update, **({"route": "guard"} if record["verdict"] == "PASS" else self.recover_route(s))}

    def guarding(self, s):
        c = s["active_component"]
        rows = {r.evidence_id: r for r in self.rows(s)}
        latest = s["verification_results"][c][-1]
        formula = FORMULAS[s["formula_id"]]
        denominator_periods = (s["required_periods"][-1:] if s["formula_id"].endswith("growth") else s["required_periods"])
        denominator_component = formula.components[0] if len(formula.components) == 1 else formula.components[1]
        result = guard(rows[s["proposed_id"]], latest["evidence_id"] if latest["verdict"] == "PASS" else None,
                       denominator_periods if c == denominator_component else ())
        update = {"guard_results": {**s["guard_results"], c: s["guard_results"].get(c, []) + [result]}}
        if result["passed"]:
            return {**update, "accepted_evidence": {**s["accepted_evidence"], c: s["proposed_id"]}, "route": "next_component"}
        failed = ", ".join(key for key, passed in result["checks"].items() if not passed)
        recovery = self.recover_route(s)
        warnings = recovery.pop("warnings", s["warnings"])
        return {**update, **recovery, "warnings": warnings + [f"Evidence {s['proposed_id']} failed deterministic checks: {failed}."]}

    def correction(self, s):
        if s["correction_attempts"] >= self.settings.correction_budget:
            return self.recover_route(s)
        c = s["active_component"]
        latest_review = s["verification_results"].get(c, [])[-1:]
        if self.settings.qwen_enabled and latest_review and latest_review[0].get("method") == "qwen" and latest_review[0]["verdict"] != "PASS" and not latest_review[0].get("findings"):
            from ..agents.verification_contract import VerifierContractError
            raise VerifierContractError("Recovery requires an accepted source-grounded verifier finding; unvalidated model prose cannot trigger expansion")
        rows = {r.evidence_id: r for r in self.rows(s)}
        ranked = s["top_k_candidates"][c] if s["candidate_scope"] == "TOP_K" else s["retrieval_results"][c]
        # A model cannot repair immutable missing/invalid fact metadata by
        # returning the exact same source row again.
        failed_ids = {r["evidence_id"] for r in s["guard_results"].get(c, []) if not r["passed"]}
        ranked = [r for r in ranked if r["evidence_id"] not in failed_ids]
        rejected_ids = self.review_rejections(s, c)
        ranked = [r for r in ranked if r["evidence_id"] not in rejected_ids]
        ranked = [r for r in ranked if eligibility(rows[r["evidence_id"]], c, s["required_periods"],
                  s["filing_hash"], set(rows))["passed"]]
        ranked = [r for r in ranked if assess_scope(rows[r["evidence_id"]], list(rows.values()),
                  s["required_periods"], s.get("filing_metadata", {}))["status"] != "RESTRICTED"]
        policy = revenue_policy(list(rows.values()), s["required_periods"], s["filing_hash"]) if c == "revenue" else None
        if policy is not None:
            ranked = [r for r in ranked if assess_revenue_basis(rows[r["evidence_id"]], policy)["status"] == "PASS"]
        if not self.settings.qwen_enabled:
            choices = [r for r in ranked if assess_concept(rows[r["evidence_id"]], c, s["required_periods"], s["filing_hash"], set(rows), revenue_basis_policy=policy)["status"] == "PASS"]
            decision = {"decision": "REPLACE" if len(choices) == 1 else "NO_VALID_EVIDENCE",
                        "evidence_id": choices[0]["evidence_id"] if len(choices) == 1 else None,
                        "reason": "Unique existing row satisfies registered concept rules" if len(choices) == 1 else "No unique rule-supported replacement; no model decision was requested",
                        "method": "deterministic_concept_rules"}
            update = {"correction_attempts": s["correction_attempts"] + 1, "correction_count": s["correction_count"] + 1,
                      "correction_results": {**s["correction_results"], c: s["correction_results"].get(c, []) + [decision]}}
            if len(choices) == 1:
                return {**update, "proposed_id": decision["evidence_id"], "route": "verify"}
            if s["component_expansions"] < self.settings.expansion_budget:
                return {**update, "route": "expand_search"}
            return {**update, "final_status": "INSUFFICIENT_EVIDENCE", "warnings": s["warnings"] + [decision["reason"]]}
        chunks, chunk, size = [], [], 0
        for candidate in ranked:
            cost = len(json.dumps(self.decoder_evidence(rows[candidate["evidence_id"]], s["required_periods"])))
            if chunk and (len(chunk) >= self.settings.correction_chunk_size or size + cost > self.settings.decoder_context):
                chunks.append(chunk)
                chunk, size = [], 0
            chunk.append(candidate)
            size += cost
        if chunk:
            chunks.append(chunk)
        decisions = []
        result = None
        for chunk in chunks[:self.settings.max_correction_chunks]:
            payload = {**self.model_payload(s), "available_candidates": [self.decoder_evidence(rows[r["evidence_id"]], s["required_periods"]) for r in chunk],
                "rejected_selection": s["proposed_id"],
                "verification": [{k: record[k] for k in ("evidence_id", "verdict", "error_type", "findings", "checks", "scope_assessment") if k in record}
                                 for record in s["verification_results"].get(c, [])[-1:]],
                "guard": s["guard_results"].get(c, [])[-1:], "search_scope": s["candidate_scope"],
                "previous_corrections": s["correction_results"].get(c, [])[-1:],
                "expansion_allowed": s["component_expansions"] < self.settings.expansion_budget}
            result = correct(self.decoder, payload)
            decisions.append(result.model_dump(mode="json"))
            if result.decision in {"REPLACE", "EXPAND_SEARCH"}:
                break
        update = {"correction_attempts": s["correction_attempts"] + 1,
                  "correction_count": s["correction_count"] + 1,
                  "correction_results": {**s["correction_results"], c: s["correction_results"].get(c, []) + decisions}}
        if len(chunks) > self.settings.max_correction_chunks:
            update["warnings"] = s["warnings"] + ["Correction candidate budget limited inspection; uninspected rows remain unresolved"]
        if result and result.decision == "REPLACE":
            return {**update, "proposed_id": result.evidence_id, "route": "verify"}
        if s["component_expansions"] < self.settings.expansion_budget:
            return {**update, "route": "expand_search"}
        if result and result.decision == "EXPAND_SEARCH" and update["correction_attempts"] < self.settings.correction_budget:
            return {**update, "route": "correct"}
        return {**update, "final_status": "INSUFFICIENT_EVIDENCE", "warnings": update.get("warnings", s["warnings"]) + ["No valid replacement evidence established"]}

    def next_component(self, s):
        index = s["component_index"] + 1
        return {"component_index": index, "route": "retrieve_component" if index < len(s["required_components"]) else "calculate"}

    def calculation(self, s):
        plan = TaskPlan.model_validate(s["task_plan"])
        rows = {r.evidence_id: r for r in self.rows(s)}
        accepted = {c: rows[ident] for c, ident in s["accepted_evidence"].items()}
        verified = {c: records[-1]["evidence_id"] for c, records in s["verification_results"].items() if records[-1]["verdict"] == "PASS"}
        try:
            result = calculate(plan, accepted, verified)
        except EvidenceError as exc:
            c = s["active_component"]
            accepted_ids = {key: value for key, value in s["accepted_evidence"].items() if key != c}
            return {"accepted_evidence": accepted_ids, "warnings": s["warnings"] + [str(exc)], **self.recover_route(s)}
        warnings = s["warnings"]
        if any(f.currency is None for row in accepted.values() for f in row.facts if f.period in plan.required_periods):
            warnings = warnings + ["Currency code is unspecified in the converted HTML. The calculation uses a common explicitly monetary table basis; currency cancels in this percentage/ratio. No USD denomination was assumed."]
        return {"calculation_result": result.model_dump(mode="json"), "final_status": "SUCCESS", "warnings": warnings}

    def finish(self, s):
        rows = {r.evidence_id: r for r in self.rows(s)} if s.get("evidence_artifact_reference") else {}
        revenue_review = s["verification_results"].get("revenue", [])[-1:]
        basis = (revenue_review[0].get("concept_assessment", {}).get("revenue_basis")
                 if revenue_review and revenue_review[0]["evidence_id"] == s["accepted_evidence"].get("revenue") else None)
        return {"final_response": {"status": s["final_status"], "calculation": s.get("calculation_result"),
            "evidence": {c: rows[ident].model_dump(mode="json") for c, ident in s["accepted_evidence"].items()},
            "revenue_basis": basis, "filing_metadata": s["filing_metadata"], "warnings": s["warnings"], "errors": s["errors"]}}

    def wrapped(self, name, function):
        def invoke(state):
            started = time.perf_counter()
            self.notify("started", name, state)
            try:
                update = function(copy.deepcopy(state))
            except EvidenceError as exc:
                update = {"final_status": "INSUFFICIENT_EVIDENCE", "warnings": state["warnings"] + [str(exc)]}
            except Exception as exc:
                update = {"final_status": "ERROR", "errors": state["errors"] + [{"node": name, "type": type(exc).__name__, "message": str(exc)}]}
            elapsed = time.perf_counter() - started
            calls = getattr(self.decoder, "calls", [])
            update["decoder_call_count"] = len(calls)
            update["timings"] = {**update.get("timings", state["timings"]), name: state["timings"].get(name, 0) + elapsed}
            details = {k: v for k, v in update.items() if k not in {"audit_events", "timings"}}
            update["audit_events"] = update.get("audit_events", state["audit_events"]) + [self.audit.event(name, elapsed, details)]
            current = {**state, **update}
            self.latest_state = current
            try:
                self.audit.save(current, calls)
                update["warnings"] = list(dict.fromkeys(current["warnings"] + self.audit.warnings))
            except OSError as exc:
                update.update(self.audit_failure(current, exc))
            self.latest_state = {**state, **update}
            self.notify("completed", name, self.latest_state, elapsed)
            return update
        return invoke

    def run(self, question, source, periods=None, on_progress=None, *, formula_id=None,
            supplementary_sources=None, use_cached_filings=False):
        self.on_progress = on_progress
        self.selected_formula = formula_id
        self.supplementary_sources = supplementary_sources or []
        self.use_cached_filings = use_cached_filings
        if hasattr(self.decoder, "calls"):
            self.decoder.calls.clear()
        self.requested_periods = periods
        request_id = uuid.uuid4().hex
        state = {"request_id": request_id, "user_question": question, "filing_source": source,
            "requested_filing_source": source, "input_inventory": [],
            "filing_metadata": {}, "filing_hash": "", "parsed_statements": [], "task_plan": {},
            "retrieval_results": {}, "top_k_candidates": {}, "retrieval_diagnostics": {}, "evidence_sufficiency": {},
            "verification_results": {}, "correction_results": {}, "accepted_evidence": {}, "guard_results": {},
            "calculation_result": None, "final_status": "", "warnings": [], "errors": [], "audit_events": [],
            "timings": {}, "decoder_call_count": 0, "expanded_search_count": 0, "correction_count": 0,
            "config_version": self.settings.config_version, "config_hash": self.settings.fingerprint(),
            "model_versions": {"finbert": self.settings.finbert_model, "revision": self.settings.finbert_revision,
                "decoder": getattr(self.decoder, "version", {"name": self.settings.decoder_model}),
                "prompt_version": self.settings.prompt_version, "formula_version": self.settings.formula_version,
                "timestamp": datetime.now(timezone.utc).isoformat()}}
        self.latest_state = state
        try:
            self.audit = Audit(self.settings, request_id)
        except OSError as exc:
            result = {**state, **self.audit_failure(state, exc), "audit_path": None, "audit_complete": False}
            result.update(self.finish(result))
            return result
        methods = {"validate_request": self.validate_request, "load_filing": self.load, "plan_task": self.plan,
            "build_evidence": self.evidence, "retrieve_component": self.retrieve, "assess_sufficiency": self.sufficiency,
            "check_inputs": self.check_inputs,
            "expand_search": self.expand, "verify": self.verification, "guard": self.guarding,
            "correct": self.correction, "next_component": self.next_component, "calculate": self.calculation, "finish": self.finish}
        graph = build_graph({name: self.wrapped(name, fn) for name, fn in methods.items()})
        started = time.perf_counter()
        try:
            result = graph.invoke(state, {"recursion_limit": 500})
        except Exception as exc:
            # Recover the newest in-memory state, not a potentially stale or
            # locked disk snapshot. This also avoids locale-dependent decoding
            # and a second exception masking the original graph failure.
            saved = self.latest_state
            result = {**saved, "final_status": "ERROR", "calculation_result": None,
                      "errors": saved["errors"] + [{"node": "graph", "type": type(exc).__name__, "message": str(exc)}]}
            try:
                result.update(self.finish(result))
            except Exception:
                result["final_response"] = {"status": "ERROR", "calculation": None, "evidence": {},
                    "filing_metadata": result["filing_metadata"], "warnings": result["warnings"], "errors": result["errors"]}
        result["timings"]["total_seconds"] = time.perf_counter() - started
        result["model_versions"]["decoder"] = getattr(self.decoder, "version", result["model_versions"]["decoder"])
        result["model_versions"]["decoder_runtime"] = getattr(self.decoder, "runtime_status", {"gpu": "unknown; not probed"})
        for records in result["retrieval_diagnostics"].values():
            for diagnostic in records:
                if diagnostic.get("finbert_revision"):
                    result["model_versions"]["resolved_finbert_revision"] = diagnostic["finbert_revision"]
                    result["model_versions"]["finbert_device"] = diagnostic["finbert_device"]
        result["config"] = self.settings.model_dump(mode="json")
        from ..config import prompts, formulas
        from .cache import digest
        result["model_versions"]["prompt_hash"] = digest(Path(prompts.__file__).read_bytes())
        result["model_versions"]["formula_hash"] = digest(Path(formulas.__file__).read_bytes())
        result["runtime_versions"] = {name: importlib.metadata.version(name) for name in
            ("torch", "transformers", "langgraph", "pydantic", "streamlit", "beautifulsoup4")}
        result["runtime_versions"]["python"] = platform.python_version()
        # finish may have run before a persistence failure changed the status.
        if result["final_status"] == "ERROR":
            result["calculation_result"] = None
            result["final_response"] = {"status": "ERROR", "calculation": None, "evidence": {},
                "filing_metadata": result["filing_metadata"], "warnings": result["warnings"], "errors": result["errors"]}
        result["audit_path"] = self.audit.last_path
        result["audit_complete"] = not any(e.get("node") == "audit_persistence" for e in result["errors"])
        try:
            result["audit_path"] = self.audit.save(result, getattr(self.decoder, "calls", []))
            result["warnings"] = list(dict.fromkeys(result["warnings"] + self.audit.warnings))
            result["final_response"]["warnings"] = result["warnings"]
        except OSError as exc:
            result.update(self.audit_failure(result, exc))
            result["audit_complete"] = False
            result["final_response"] = {"status": "ERROR", "calculation": None, "evidence": {},
                "filing_metadata": result["filing_metadata"], "warnings": result["warnings"], "errors": result["errors"]}
        return result
