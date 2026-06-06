"""Pipeline trace models and SSE state_delta builders.

These models were previously the root LLM agent's output_schema; they are now assembled
deterministically in Python by the orchestrator. The state_delta builders produce the exact
shapes the UI already renders (any key with a `status` field becomes a trace step), so the
frontend is unchanged.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from agents.policy_decision_agent.agent import PolicyDecision

StepName = Literal[
    "DOCUMENT_CLASSIFICATION",
    "DOCUMENT_REQUIREMENTS",
    "DOCUMENT_EXTRACTION",
    "CONSISTENCY_CHECK",
    "POLICY_DECISION",
]

StepStatus = Literal[
    "COMPLETED",
    "SKIPPED",
    "BLOCKED",
    "PENDING_REUPLOAD",
    "MANUAL_REVIEW_RECOMMENDED",
]

FinalStatus = Literal[
    "APPROVED",
    "PARTIAL",
    "REJECTED",
    "MANUAL_REVIEW",
    "STOPPED_AT_GATE",
    "STOPPED_AT_CONSISTENCY",
    "PENDING_MEMBER_ACTION",
    "MANUAL_REVIEW_RECOMMENDED",
]


class PipelineStepResult(BaseModel):
    step_name: StepName
    status: StepStatus
    summary: str
    key_findings: list[str] = Field(default_factory=list, description="Short bullets; keep <= 5 items.")


class PipelineTrace(BaseModel):
    steps: list[PipelineStepResult] = Field(default_factory=list)
    final_status: FinalStatus
    final_member_message: str
    final_ops_summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    policy_decision: PolicyDecision | None = Field(default=None)


def stage_state_delta(
    step_name: str,
    status: str,
    summary: str,
    key_findings: list[str] | None = None,
    *,
    ops_message: str | None = None,
    member_message: str | None = None,
) -> dict[str, Any]:
    """state_delta for a single stage event (UI renders any key with a `status` field)."""
    return {
        step_name: {
            "status": status,
            "summary": summary,
            "key_findings": key_findings or [],
            "ops_message": ops_message,
            "member_message": member_message,
        }
    }


def final_state_delta(trace: PipelineTrace) -> dict[str, Any]:
    """Flattened final state_delta — same keys the previous ADK flattening produced."""
    delta: dict[str, Any] = {
        "final_member_message": trace.final_member_message,
        "final_ops_summary": trace.final_ops_summary,
        "final_status": trace.final_status,
        "blockers": trace.blockers,
        "warnings": trace.warnings,
        "policy_decision": trace.policy_decision.model_dump() if trace.policy_decision else None,
    }
    for s in trace.steps:
        delta[s.step_name] = {
            "status": s.status,
            "summary": s.summary,
            "key_findings": s.key_findings,
            "ops_message": None,
            "member_message": None,
        }
    return delta
