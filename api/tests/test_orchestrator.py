import pytest

import pipeline.orchestrator as orch
from agents.consistency_check_agent.agent import ConsistencyCheckResult
from agents.document_extraction_agent.agent import DocumentExtractionResult
from agents.document_gate_agent.agent import DocumentClassificationResult
from agents.document_requirements_agent.agent import DocumentRequirementsResult


async def _collect(gen):
    return [e async for e in gen]


def _gate(outcome="PASS", ptype="PRESCRIPTION", fid="F1"):
    return DocumentClassificationResult(
        file_id=fid, file_name=f"{fid}.pdf", predicted_type=ptype,
        confidence_score=0.9, confidence_band="HIGH", gate_outcome=outcome, ops_message="")


def _claim():
    return {
        "claim_category": "CONSULTATION", "member_id": "EMP001", "policy_id": "P1",
        "treatment_date": "2024-11-01", "claimed_amount": 4200.0,
        "has_pre_authorization": False, "relationship_claim_type": "SELF",
        "patient_member_id": None, "claims_history": [],
    }


def _docs():
    return [{"file_id": "F1", "file_name": "F1.pdf", "document_text": "t"}]


def _stage_names(events):
    return [e["step_name"] for e in events if e["type"] == "stage"]


def _final(events):
    return events[-1]


@pytest.mark.asyncio
async def test_gate_fail_stops_at_classification(monkeypatch):
    monkeypatch.setattr(orch, "classify_document", lambda d: _gate("PENDING_REUPLOAD", "UNKNOWN"))
    events = await _collect(orch.run_claim_pipeline(_claim(), _docs()))
    assert _stage_names(events) == ["DOCUMENT_CLASSIFICATION"]
    assert _final(events)["state_delta"]["final_status"] == "PENDING_MEMBER_ACTION"


@pytest.mark.asyncio
async def test_requirements_blocked(monkeypatch):
    monkeypatch.setattr(orch, "classify_document", lambda d: _gate("PASS"))
    monkeypatch.setattr(orch, "check_requirements", lambda c, t: DocumentRequirementsResult(
        outcome="BLOCKED", claim_category="CONSULTATION", ops_message="blocked"))
    events = await _collect(orch.run_claim_pipeline(_claim(), _docs()))
    assert _stage_names(events) == ["DOCUMENT_CLASSIFICATION", "DOCUMENT_REQUIREMENTS"]
    assert _final(events)["state_delta"]["final_status"] == "STOPPED_AT_GATE"


@pytest.mark.asyncio
async def test_requirements_pending(monkeypatch):
    monkeypatch.setattr(orch, "classify_document", lambda d: _gate("PASS"))
    monkeypatch.setattr(orch, "check_requirements", lambda c, t: DocumentRequirementsResult(
        outcome="PENDING_REUPLOAD", claim_category="CONSULTATION",
        missing_required_types=["HOSPITAL_BILL"], ops_message="need bill"))
    events = await _collect(orch.run_claim_pipeline(_claim(), _docs()))
    assert _final(events)["state_delta"]["final_status"] == "PENDING_MEMBER_ACTION"


def _ext():
    return DocumentExtractionResult(file_id="F1", file_name="F1.pdf", document_type="PRESCRIPTION",
        extraction_confidence=0.9, ops_message="")


@pytest.mark.asyncio
async def test_consistency_blocked(monkeypatch):
    monkeypatch.setattr(orch, "classify_document", lambda d: _gate("PASS"))
    monkeypatch.setattr(orch, "check_requirements", lambda c, t: DocumentRequirementsResult(
        outcome="PASS", claim_category="CONSULTATION", ops_message="ok"))
    monkeypatch.setattr(orch, "extract_document", lambda d: _ext())
    monkeypatch.setattr(orch, "build_consistency_snapshots", lambda r: [])
    monkeypatch.setattr(orch, "check_consistency", lambda s, **k: ConsistencyCheckResult(
        outcome="BLOCKED", confidence_score=0.9, ops_message="mismatch"))
    events = await _collect(orch.run_claim_pipeline(_claim(), _docs()))
    assert _final(events)["state_delta"]["final_status"] == "STOPPED_AT_CONSISTENCY"
    assert "POLICY_DECISION" not in _stage_names(events)


@pytest.mark.asyncio
async def test_happy_path_approved(monkeypatch):
    monkeypatch.setattr(orch, "classify_document", lambda d: _gate("PASS"))
    monkeypatch.setattr(orch, "check_requirements", lambda c, t: DocumentRequirementsResult(
        outcome="PASS", claim_category="CONSULTATION", ops_message="ok"))
    monkeypatch.setattr(orch, "extract_document", lambda d: _ext())
    monkeypatch.setattr(orch, "build_consistency_snapshots", lambda r: [])
    monkeypatch.setattr(orch, "check_consistency", lambda s, **k: ConsistencyCheckResult(
        outcome="PASS", confidence_score=0.95, ops_message="consistent"))
    monkeypatch.setattr(orch, "run_policy_decision", lambda **k: {
        "decision": "APPROVED", "approved_amount": 4200.0, "copay_amount": 0.0,
        "reason": "All checks passed", "confidence_score": 0.99, "rule_findings": []})
    events = await _collect(orch.run_claim_pipeline(_claim(), _docs()))
    assert _stage_names(events) == [
        "DOCUMENT_CLASSIFICATION", "DOCUMENT_REQUIREMENTS", "DOCUMENT_EXTRACTION",
        "CONSISTENCY_CHECK", "POLICY_DECISION"]
    final = _final(events)["state_delta"]
    assert final["final_status"] == "APPROVED"
    assert final["policy_decision"]["approved_amount"] == 4200.0


@pytest.mark.asyncio
async def test_consistency_manual_review_continues(monkeypatch):
    monkeypatch.setattr(orch, "classify_document", lambda d: _gate("PASS"))
    monkeypatch.setattr(orch, "check_requirements", lambda c, t: DocumentRequirementsResult(
        outcome="PASS", claim_category="CONSULTATION", ops_message="ok"))
    monkeypatch.setattr(orch, "extract_document", lambda d: _ext())
    monkeypatch.setattr(orch, "build_consistency_snapshots", lambda r: [])
    monkeypatch.setattr(orch, "check_consistency", lambda s, **k: ConsistencyCheckResult(
        outcome="MANUAL_REVIEW_RECOMMENDED", confidence_score=0.6, ops_message="soft mismatch"))
    monkeypatch.setattr(orch, "run_policy_decision", lambda **k: {
        "decision": "PARTIAL", "approved_amount": 2000.0, "copay_amount": 200.0,
        "reason": "partial", "confidence_score": 0.8, "rule_findings": []})
    events = await _collect(orch.run_claim_pipeline(_claim(), _docs()))
    assert "POLICY_DECISION" in _stage_names(events)
    final = _final(events)["state_delta"]
    assert final["final_status"] == "PARTIAL"
    assert final["warnings"] == ["soft mismatch"]


@pytest.mark.asyncio
async def test_policy_exception_manual_review(monkeypatch):
    monkeypatch.setattr(orch, "classify_document", lambda d: _gate("PASS"))
    monkeypatch.setattr(orch, "check_requirements", lambda c, t: DocumentRequirementsResult(
        outcome="PASS", claim_category="CONSULTATION", ops_message="ok"))
    monkeypatch.setattr(orch, "extract_document", lambda d: _ext())
    monkeypatch.setattr(orch, "build_consistency_snapshots", lambda r: [])
    monkeypatch.setattr(orch, "check_consistency", lambda s, **k: ConsistencyCheckResult(
        outcome="PASS", confidence_score=0.95, ops_message="ok"))

    def boom(**k):
        raise RuntimeError("db down")

    monkeypatch.setattr(orch, "run_policy_decision", boom)
    events = await _collect(orch.run_claim_pipeline(_claim(), _docs()))
    assert _final(events)["state_delta"]["final_status"] == "MANUAL_REVIEW"
