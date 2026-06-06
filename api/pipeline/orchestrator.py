"""Deterministic claim pipeline — the state machine that replaces the LLM orchestrator.

Async generator: yields one `{"type": "stage", ...}` event per stage and a final
`{"type": "final", "state_delta": ..., "trace": ...}` event. Control flow is explicit Python;
the LLM is only invoked inside the stage functions (understanding), never to decide flow.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from agents.policy_decision_agent.agent import PolicyDecision, run_policy_decision
from pipeline.stages import (
    build_consistency_snapshots,
    check_consistency,
    check_requirements,
    classify_document,
    extract_document,
)
from pipeline.trace import (
    PipelineStepResult,
    PipelineTrace,
    final_state_delta,
    stage_state_delta,
)


def _stage_event(step_name: str, status: str, summary: str, findings: list[str]) -> dict[str, Any]:
    return {
        "type": "stage",
        "step_name": step_name,
        "state_delta": stage_state_delta(step_name, status, summary, findings[:5]),
    }


def _final_event(trace: PipelineTrace) -> dict[str, Any]:
    return {"type": "final", "state_delta": final_state_delta(trace), "trace": trace.model_dump()}


async def run_claim_pipeline(
    claim_input: dict[str, Any],
    documents: list[dict[str, Any]],
) -> AsyncIterator[dict[str, Any]]:
    """Run the deterministic claim pipeline, yielding SSE-ready events per stage and a final."""
    steps: list[PipelineStepResult] = []
    blockers: list[str] = []
    warnings: list[str] = []

    # ----- Stage 1: DOCUMENT_CLASSIFICATION -----------------------------------
    classifications = [classify_document(d) for d in documents]
    findings = [f"{c.file_name}: {c.predicted_type} ({c.gate_outcome})" for c in classifications]
    pending = [c for c in classifications if c.gate_outcome == "PENDING_REUPLOAD"]
    if pending:
        steps.append(PipelineStepResult(
            step_name="DOCUMENT_CLASSIFICATION", status="PENDING_REUPLOAD",
            summary=f"{len(pending)} of {len(classifications)} document(s) could not be classified.",
            key_findings=findings))
        yield _stage_event("DOCUMENT_CLASSIFICATION", "PENDING_REUPLOAD",
                           steps[-1].summary, findings)
        blockers = [f"{c.file_name} ({c.file_id}): not enough signal to classify" for c in pending]
        member_msg = " ".join(
            f"The document '{c.file_name}' could not be read clearly — please re-upload a clear copy."
            for c in pending)
        trace = PipelineTrace(steps=steps, final_status="PENDING_MEMBER_ACTION",
            final_member_message=member_msg,
            final_ops_summary="Pipeline stopped at DOCUMENT_CLASSIFICATION; documents need re-upload.",
            blockers=blockers, warnings=warnings)
        yield _final_event(trace)
        return
    steps.append(PipelineStepResult(
        step_name="DOCUMENT_CLASSIFICATION", status="COMPLETED",
        summary=f"Classified all {len(classifications)} document(s).", key_findings=findings))
    yield _stage_event("DOCUMENT_CLASSIFICATION", "COMPLETED", steps[-1].summary, findings)

    # ----- Stage 2: DOCUMENT_REQUIREMENTS -------------------------------------
    predicted_types = [c.predicted_type for c in classifications]
    req = check_requirements(claim_input["claim_category"], predicted_types)
    req_findings = list(req.key_findings) or [req.ops_message]
    if req.outcome == "BLOCKED":
        steps.append(PipelineStepResult(step_name="DOCUMENT_REQUIREMENTS", status="BLOCKED",
            summary=req.ops_message, key_findings=req_findings))
        yield _stage_event("DOCUMENT_REQUIREMENTS", "BLOCKED", req.ops_message, req_findings)
        trace = PipelineTrace(steps=steps, final_status="STOPPED_AT_GATE",
            final_member_message=req.ops_message,
            final_ops_summary="Pipeline stopped at DOCUMENT_REQUIREMENTS (blocked).",
            blockers=[req.ops_message] + [f"Missing: {t}" for t in req.missing_required_types],
            warnings=warnings)
        yield _final_event(trace)
        return
    if req.outcome == "PENDING_REUPLOAD":
        steps.append(PipelineStepResult(step_name="DOCUMENT_REQUIREMENTS", status="PENDING_REUPLOAD",
            summary=req.ops_message, key_findings=req_findings))
        yield _stage_event("DOCUMENT_REQUIREMENTS", "PENDING_REUPLOAD", req.ops_message, req_findings)
        trace = PipelineTrace(steps=steps, final_status="PENDING_MEMBER_ACTION",
            final_member_message=req.ops_message,
            final_ops_summary="Pipeline stopped at DOCUMENT_REQUIREMENTS; member action required.",
            blockers=[f"Missing required: {t}" for t in req.missing_required_types],
            warnings=warnings)
        yield _final_event(trace)
        return
    steps.append(PipelineStepResult(step_name="DOCUMENT_REQUIREMENTS", status="COMPLETED",
        summary=req.ops_message or "Document requirements satisfied.", key_findings=req_findings))
    yield _stage_event("DOCUMENT_REQUIREMENTS", "COMPLETED", steps[-1].summary, req_findings)

    # ----- Stage 3: DOCUMENT_EXTRACTION ---------------------------------------
    extraction_results = [
        extract_document({**d, "document_type": c.predicted_type})
        for d, c in zip(documents, classifications)
    ]
    ext_findings = [f"{r.file_name}: {r.document_type} (conf {r.extraction_confidence:.2f})"
                    for r in extraction_results]
    steps.append(PipelineStepResult(step_name="DOCUMENT_EXTRACTION", status="COMPLETED",
        summary=f"Extracted fields from {len(extraction_results)} document(s).", key_findings=ext_findings))
    yield _stage_event("DOCUMENT_EXTRACTION", "COMPLETED", steps[-1].summary, ext_findings)

    # ----- Stage 4: CONSISTENCY_CHECK -----------------------------------------
    snapshots = build_consistency_snapshots(extraction_results)
    cons = check_consistency(snapshots, claimed_amount=claim_input.get("claimed_amount"),
                             treatment_date=claim_input.get("treatment_date"))
    cons_findings = list(cons.key_findings) or [cons.ops_message]
    if cons.outcome == "BLOCKED":
        steps.append(PipelineStepResult(step_name="CONSISTENCY_CHECK", status="BLOCKED",
            summary=cons.ops_message, key_findings=cons_findings))
        yield _stage_event("CONSISTENCY_CHECK", "BLOCKED", cons.ops_message, cons_findings)
        trace = PipelineTrace(steps=steps, final_status="STOPPED_AT_CONSISTENCY",
            final_member_message=cons.ops_message,
            final_ops_summary="Pipeline stopped at CONSISTENCY_CHECK (contradictions found).",
            blockers=[i.description for i in cons.issues] or [cons.ops_message], warnings=warnings)
        yield _final_event(trace)
        return
    if cons.outcome == "MANUAL_REVIEW_RECOMMENDED":
        warnings.append(cons.ops_message)
        steps.append(PipelineStepResult(step_name="CONSISTENCY_CHECK",
            status="MANUAL_REVIEW_RECOMMENDED", summary=cons.ops_message, key_findings=cons_findings))
        yield _stage_event("CONSISTENCY_CHECK", "MANUAL_REVIEW_RECOMMENDED", cons.ops_message, cons_findings)
    else:
        steps.append(PipelineStepResult(step_name="CONSISTENCY_CHECK", status="COMPLETED",
            summary=cons.ops_message or "Documents are consistent.", key_findings=cons_findings))
        yield _stage_event("CONSISTENCY_CHECK", "COMPLETED", steps[-1].summary, cons_findings)

    # ----- Stage 5: POLICY_DECISION (pure Python) -----------------------------
    policy_decision: PolicyDecision | None = None
    try:
        decision_dict = run_policy_decision(
            member_id=claim_input["member_id"],
            policy_id=claim_input["policy_id"],
            claim_category=claim_input["claim_category"],
            treatment_date=claim_input["treatment_date"],
            claimed_amount=claim_input["claimed_amount"],
            has_pre_authorization=claim_input.get("has_pre_authorization", False),
            relationship_claim_type=claim_input.get("relationship_claim_type", "SELF"),
            patient_member_id=claim_input.get("patient_member_id"),
            extracted_documents_json=json.dumps([r.model_dump() for r in extraction_results]),
            claims_history_json=json.dumps(claim_input.get("claims_history", [])),
        )
        policy_decision = PolicyDecision.model_validate(decision_dict)
        final_status = policy_decision.decision
        decision_summary = policy_decision.reason
        member_msg = policy_decision.reason
        step_status = "MANUAL_REVIEW_RECOMMENDED" if final_status == "MANUAL_REVIEW" else "COMPLETED"
    except Exception as exc:  # deterministic engine error → manual review, never a crash
        final_status = "MANUAL_REVIEW"
        decision_summary = f"Policy decision could not be computed: {exc}"
        member_msg = "Your claim needs a manual review by our team."
        step_status = "MANUAL_REVIEW_RECOMMENDED"

    steps.append(PipelineStepResult(step_name="POLICY_DECISION", status=step_status,
        summary=decision_summary, key_findings=[f"Decision: {final_status}"]))
    yield _stage_event("POLICY_DECISION", step_status, decision_summary, [f"Decision: {final_status}"])

    trace = PipelineTrace(steps=steps, final_status=final_status, final_member_message=member_msg,
        final_ops_summary=f"Pipeline completed with decision {final_status}.",
        blockers=blockers, warnings=warnings, policy_decision=policy_decision)
    yield _final_event(trace)
