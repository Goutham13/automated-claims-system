# Deterministic Python Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the LLM root orchestrator with a deterministic Python pipeline that calls each understanding stage as a typed `google-genai` controlled-generation call, keeping `run_policy_decision` pure-Python and the SSE/UI contract unchanged.

**Architecture:** New `api/pipeline/` package — `llm.py` (single model call-site), `stages.py` (typed stage functions + deterministic snapshot mapping, reusing existing prompts/schemas), `orchestrator.py` (explicit state machine, async generator of SSE events), `trace.py` (PipelineTrace + event builders). `main.py` calls the orchestrator instead of an ADK runner. The root LLM agent and ADK request-path usage are removed.

**Tech Stack:** Python 3.11+, google-genai (Vertex), Pydantic v2, pytest.

**Reference spec:** `docs/superpowers/specs/2026-06-07-deterministic-orchestrator-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `api/pipeline/llm.py` | `structured_llm_call(system_prompt, payload, output_model, client=None)` — one genai call. |
| `api/pipeline/trace.py` | `PipelineStepResult`, `PipelineTrace`, `stage_state_delta()`, `final_state_delta()`. |
| `api/pipeline/stages.py` | `classify_document`, `check_requirements`, `extract_document`, `check_consistency`, `build_consistency_snapshots`. |
| `api/pipeline/orchestrator.py` | `run_claim_pipeline()` — async generator yielding stage/final events. |
| `api/main.py` (modify) | Call `run_claim_pipeline`; drop ADK runner + flatten helpers. |
| `api/agents/*/agent.py` (modify) | Drop `LlmAgent` objects; keep `PROMPT` + schemas. |
| `api/agents/agent.py` (delete) | Root orchestrator removed. |

**Reused prompt/schema names (verified):**
- gate: `DOCUMENT_GATE_PROMPT`, `UploadedDocumentInput`, `DocumentClassificationResult`
- requirements: `DOCUMENT_REQUIREMENTS_PROMPT`, `DocumentRequirementsInput`, `DocumentRequirementsResult`
- extraction: `DOCUMENT_EXTRACTION_PROMPT`, `ExtractionInputDocument`, `DocumentExtractionResult`
- consistency: `CONSISTENCY_CHECK_PROMPT`, `DocumentConsistencySnapshot`, `ConsistencyCheckInput`, `ConsistencyCheckResult`
- policy: `run_policy_decision(...)`, `PolicyDecision`

---

### Task 1: `pipeline/llm.py` — single model call-site

**Files:** Create `api/pipeline/__init__.py`, `api/pipeline/llm.py`, `api/tests/test_llm.py`

- [ ] **Step 1: Failing test** — `api/tests/test_llm.py`
```python
from pydantic import BaseModel
from pipeline.llm import structured_llm_call


class Out(BaseModel):
    label: str
    score: float


class FakeModels:
    def __init__(self, parsed): self._parsed = parsed; self.calls = []
    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        class R: pass
        r = R(); r.parsed = self._parsed; r.text = self._parsed.model_dump_json()
        return r


class FakeClient:
    def __init__(self, parsed): self.models = FakeModels(parsed)


def test_structured_call_returns_parsed_model():
    client = FakeClient(Out(label="PRESCRIPTION", score=0.9))
    out = structured_llm_call("sys", {"document_text": "x"}, Out, client=client)
    assert isinstance(out, Out) and out.label == "PRESCRIPTION"
    cfg = client.models.calls[0]["config"]
    assert cfg.response_schema is Out
    assert cfg.response_mime_type == "application/json"
    assert cfg.system_instruction == "sys"


def test_falls_back_to_text_when_parsed_missing():
    client = FakeClient(Out(label="HOSPITAL_BILL", score=0.5))
    client.models._parsed = None  # force .parsed = None path via text
    # craft a client whose parsed is None but text is valid JSON
    class M:
        def generate_content(self, **k):
            class R: pass
            r = R(); r.parsed = None; r.text = '{"label":"HOSPITAL_BILL","score":0.5}'
            return r
    class C: models = M()
    out = structured_llm_call("sys", {"a": 1}, Out, client=C())
    assert out.label == "HOSPITAL_BILL"
```

- [ ] **Step 2: Run → fails** (`uv run pytest tests/test_llm.py -q`) — ModuleNotFoundError.

- [ ] **Step 3: Implement** — `api/pipeline/__init__.py` (`"""Deterministic claims pipeline."""`) and `api/pipeline/llm.py`:
```python
"""Single model call-site for the deterministic pipeline (google-genai controlled generation)."""
from __future__ import annotations

import json
import os
from typing import Any, TypeVar

from google import genai
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

_client: genai.Client | None = None
DEFAULT_MODEL = os.getenv("PIPELINE_MODEL", "gemini-3-flash-preview")


def _default_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()  # reads GOOGLE_GENAI_USE_VERTEXAI / project / location from env
    return _client


def structured_llm_call(
    system_prompt: str,
    payload: BaseModel | dict[str, Any],
    output_model: type[T],
    *,
    model: str | None = None,
    client: Any | None = None,
) -> T:
    """Call the model with a typed payload and parse the JSON response into output_model."""
    payload_str = payload.model_dump_json() if isinstance(payload, BaseModel) else json.dumps(payload)
    cli = client or _default_client()
    resp = cli.models.generate_content(
        model=model or DEFAULT_MODEL,
        contents=payload_str,
        config=GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=output_model,
            temperature=0.1,
        ),
    )
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, output_model):
        return parsed
    return output_model.model_validate_json(resp.text)
```

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Commit** — `feat(pipeline): add structured_llm_call single model call-site`

---

### Task 2: `pipeline/trace.py` — trace models + event builders

**Files:** Create `api/pipeline/trace.py`, `api/tests/test_trace.py`

- [ ] **Step 1: Failing test** — `api/tests/test_trace.py`
```python
from pipeline.trace import PipelineTrace, PipelineStepResult, stage_state_delta, final_state_delta


def test_stage_state_delta_shape():
    d = stage_state_delta("DOCUMENT_CLASSIFICATION", "COMPLETED", "ok", ["a", "b"])
    step = d["DOCUMENT_CLASSIFICATION"]
    assert step["status"] == "COMPLETED" and step["key_findings"] == ["a", "b"]


def test_final_state_delta_carries_summary_keys():
    trace = PipelineTrace(
        steps=[PipelineStepResult(step_name="POLICY_DECISION", status="COMPLETED", summary="done")],
        final_status="APPROVED", final_member_message="m", final_ops_summary="o",
    )
    d = final_state_delta(trace)
    assert d["final_status"] == "APPROVED"
    assert d["final_member_message"] == "m"
    assert d["POLICY_DECISION"]["status"] == "COMPLETED"
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — move `PipelineStepResult` + `PipelineTrace` out of `agents/agent.py` (verbatim — same `step_name`/`status`/`final_status` Literals, `policy_decision: PolicyDecision | None`) into `api/pipeline/trace.py`, importing `PolicyDecision` from `agents.policy_decision_agent.agent`. Add builders:
```python
def stage_state_delta(step_name, status, summary, key_findings=None, *, ops_message=None, member_message=None):
    return {step_name: {"status": status, "summary": summary,
                        "key_findings": key_findings or [],
                        "ops_message": ops_message, "member_message": member_message}}

def final_state_delta(trace: "PipelineTrace") -> dict:
    d = {
        "final_member_message": trace.final_member_message,
        "final_ops_summary": trace.final_ops_summary,
        "final_status": trace.final_status,
        "blockers": trace.blockers,
        "warnings": trace.warnings,
        "policy_decision": trace.policy_decision.model_dump() if trace.policy_decision else None,
    }
    for s in trace.steps:
        d[s.step_name] = {"status": s.status, "summary": s.summary,
                          "key_findings": s.key_findings, "ops_message": None, "member_message": None}
    return d
```
(Mirrors the keys `_flatten_pipeline_trace_state_delta` produces today, so the UI is unchanged.)

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Commit** — `feat(pipeline): add PipelineTrace models and SSE event builders`

---

### Task 3: `pipeline/stages.py` — typed stage functions + snapshot mapping

**Files:** Create `api/pipeline/stages.py`, `api/tests/test_stages.py`

- [ ] **Step 1: Failing test** — `api/tests/test_stages.py` covering:
  - `build_consistency_snapshots` field mapping (prescription + hospital_bill → patient_name/primary_date/amount/diagnosis/provider_name/doctor_name correct).
  - `classify_document` calls `structured_llm_call` with gate prompt+schema (monkeypatch `pipeline.stages.structured_llm_call` to a fake returning a known result; assert passthrough).
  - `classify_document` error path → returns `DocumentClassificationResult` with `gate_outcome="PENDING_REUPLOAD"`, `predicted_type="UNKNOWN"`.
```python
import pipeline.stages as st
from agents.document_extraction_agent.agent import DocumentExtractionResult, PrescriptionFields, HospitalBillFields

def test_build_snapshots_maps_fields():
    res = [
        DocumentExtractionResult(file_id="F1", file_name="rx", document_type="PRESCRIPTION",
            extraction_confidence=0.9, ops_message="",
            prescription=PrescriptionFields(patient_name="Rajesh", prescription_date="2024-11-01",
                diagnosis_primary="Viral Fever", doctor_name="Dr A", hospital_or_clinic_name="City")),
        DocumentExtractionResult(file_id="F2", file_name="bill", document_type="HOSPITAL_BILL",
            extraction_confidence=0.9, ops_message="",
            hospital_bill=HospitalBillFields(patient_name="Rajesh", bill_date="2024-11-01",
                total_amount=4200.0, hospital_name="City Hosp", referring_doctor_name="Dr A")),
    ]
    snaps = st.build_consistency_snapshots(res)
    assert snaps[0].patient_name == "Rajesh" and snaps[0].primary_date == "2024-11-01"
    assert snaps[0].diagnosis == "Viral Fever" and snaps[0].doctor_name == "Dr A"
    assert snaps[1].amount == 4200.0 and snaps[1].provider_name == "City Hosp"

def test_classify_error_returns_pending_reupload(monkeypatch):
    def boom(*a, **k): raise RuntimeError("llm down")
    monkeypatch.setattr(st, "structured_llm_call", boom)
    r = st.classify_document({"file_id": "F1", "file_name": "x", "document_text": "t"})
    assert r.gate_outcome == "PENDING_REUPLOAD" and r.predicted_type == "UNKNOWN"
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — `api/pipeline/stages.py`:
```python
"""Typed understanding stages — each is ONE structured LLM call (reuses existing prompts/schemas)."""
from __future__ import annotations

import json

from pipeline.llm import structured_llm_call
from agents.document_gate_agent.agent import (
    DOCUMENT_GATE_PROMPT, UploadedDocumentInput, DocumentClassificationResult)
from agents.document_requirements_agent.agent import (
    DOCUMENT_REQUIREMENTS_PROMPT, DocumentRequirementsInput, DocumentRequirementsResult)
from agents.document_extraction_agent.agent import (
    DOCUMENT_EXTRACTION_PROMPT, ExtractionInputDocument, DocumentExtractionResult)
from agents.consistency_check_agent.agent import (
    CONSISTENCY_CHECK_PROMPT, DocumentConsistencySnapshot, ConsistencyCheckInput, ConsistencyCheckResult)


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def classify_document(doc: dict) -> DocumentClassificationResult:
    payload = UploadedDocumentInput(file_id=doc["file_id"], file_name=doc["file_name"],
                                    document_text=doc.get("document_text", ""))
    try:
        return structured_llm_call(DOCUMENT_GATE_PROMPT, payload, DocumentClassificationResult)
    except Exception as exc:
        return DocumentClassificationResult(
            file_id=doc["file_id"], file_name=doc["file_name"], predicted_type="UNKNOWN",
            confidence_score=0.0, confidence_band="LOW", gate_outcome="PENDING_REUPLOAD",
            ops_message=f"Classification failed: {exc}")


def check_requirements(claim_category: str, predicted_types: list[str]) -> DocumentRequirementsResult:
    payload = DocumentRequirementsInput(claim_category=claim_category, predicted_types=predicted_types)
    try:
        return structured_llm_call(DOCUMENT_REQUIREMENTS_PROMPT, payload, DocumentRequirementsResult)
    except Exception as exc:
        return DocumentRequirementsResult(outcome="BLOCKED", claim_category=claim_category,
            ops_message=f"Requirements check failed: {exc}")


def extract_document(doc: dict) -> DocumentExtractionResult:
    payload = ExtractionInputDocument(file_id=doc["file_id"], file_name=doc["file_name"],
        document_type=doc["document_type"], document_text=doc.get("document_text", ""))
    try:
        return structured_llm_call(DOCUMENT_EXTRACTION_PROMPT, payload, DocumentExtractionResult)
    except Exception as exc:
        return DocumentExtractionResult(file_id=doc["file_id"], file_name=doc["file_name"],
            document_type=doc["document_type"], extraction_confidence=0.0,
            missing_critical_fields=["ALL"], ops_message=f"Extraction failed: {exc}")


def build_consistency_snapshots(results: list[DocumentExtractionResult]) -> list[DocumentConsistencySnapshot]:
    snaps = []
    for r in results:
        rx, hb, lab, ph, dn, ds = (r.prescription, r.hospital_bill, r.lab_report,
                                   r.pharmacy_bill, r.dental_report, r.discharge_summary)
        snaps.append(DocumentConsistencySnapshot(
            file_id=r.file_id, file_name=r.file_name, document_type=r.document_type,
            patient_name=_first(*(getattr(x, "patient_name", None) for x in (rx, hb, lab, ph, dn, ds))),
            primary_date=_first(getattr(rx, "prescription_date", None), getattr(hb, "bill_date", None),
                                getattr(lab, "report_date", None), getattr(ph, "bill_date", None),
                                getattr(ds, "discharge_date", None)),
            amount=_first(getattr(hb, "total_amount", None), getattr(ph, "net_amount", None)),
            diagnosis=_first(getattr(rx, "diagnosis_primary", None), getattr(dn, "diagnosis", None),
                             getattr(ds, "final_diagnosis", None)),
            provider_name=_first(getattr(rx, "hospital_or_clinic_name", None), getattr(hb, "hospital_name", None),
                                 getattr(lab, "lab_name", None), getattr(ph, "pharmacy_name", None)),
            doctor_name=_first(getattr(rx, "doctor_name", None), getattr(hb, "referring_doctor_name", None),
                               getattr(lab, "referring_doctor_name", None)),
        ))
    return snaps


def check_consistency(snapshots: list[DocumentConsistencySnapshot], *,
                      claimed_amount=None, treatment_date=None) -> ConsistencyCheckResult:
    payload = ConsistencyCheckInput(claimed_amount=claimed_amount, treatment_date=treatment_date,
        extracted_documents=json.dumps([s.model_dump() for s in snapshots]))
    try:
        return structured_llm_call(CONSISTENCY_CHECK_PROMPT, payload, ConsistencyCheckResult)
    except Exception as exc:
        return ConsistencyCheckResult(outcome="BLOCKED",
            **{k: v for k, v in {"ops_message": f"Consistency check failed: {exc}"}.items()
               if k in ConsistencyCheckResult.model_fields})
```
> During execution, verify `ConsistencyCheckResult` required fields and adjust the error-path constructor to satisfy them (e.g. provide `issues=[]`, `ops_message`).

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Commit** — `feat(pipeline): add typed stage functions and deterministic snapshot mapping`

---

### Task 4: `pipeline/orchestrator.py` — the state machine

**Files:** Create `api/pipeline/orchestrator.py`, `api/tests/test_orchestrator.py`

- [ ] **Step 1: Failing tests** — branch coverage with `stages` monkeypatched:
  - gate `PENDING_REUPLOAD` (any file) → final event `final_status == "PENDING_MEMBER_ACTION"`, only classification ran.
  - requirements `BLOCKED` → `STOPPED_AT_GATE`.
  - requirements `PENDING_REUPLOAD` → `PENDING_MEMBER_ACTION`.
  - consistency `BLOCKED` → `STOPPED_AT_CONSISTENCY`.
  - consistency `MANUAL_REVIEW_RECOMMENDED` → warning recorded, proceeds to policy.
  - happy path → policy decision `APPROVED` → `final_status == "APPROVED"`; event order is `[DOCUMENT_CLASSIFICATION, DOCUMENT_REQUIREMENTS, DOCUMENT_EXTRACTION, CONSISTENCY_CHECK, POLICY_DECISION, final]`.
  - `run_policy_decision` raises → `MANUAL_REVIEW`.
```python
import pytest
import pipeline.orchestrator as orch
from agents.document_gate_agent.agent import DocumentClassificationResult

async def _collect(gen):
    return [e async for e in gen]

def _gate(outcome="PASS", ptype="PRESCRIPTION"):
    return DocumentClassificationResult(file_id="F1", file_name="f", predicted_type=ptype,
        confidence_score=0.9, confidence_band="HIGH", gate_outcome=outcome, ops_message="")

@pytest.mark.asyncio
async def test_gate_fail_stops(monkeypatch):
    monkeypatch.setattr(orch, "classify_document", lambda d: _gate("PENDING_REUPLOAD", "UNKNOWN"))
    claim = {"claim_category": "CONSULTATION"}
    docs = [{"file_id": "F1", "file_name": "f", "document_text": ""}]
    events = await _collect(orch.run_claim_pipeline(claim, docs))
    final = events[-1]
    assert final["type"] == "final" and final["state_delta"]["final_status"] == "PENDING_MEMBER_ACTION"
    assert [e["step_name"] for e in events if e["type"] == "stage"] == ["DOCUMENT_CLASSIFICATION"]
```
(Plus the other branches, monkeypatching `check_requirements`, `extract_document`, `build_consistency_snapshots`, `check_consistency`, and `run_policy_decision` accordingly.)

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — `api/pipeline/orchestrator.py` as an async generator that:
  - imports the stage functions from `pipeline.stages` (module-level, so tests can monkeypatch), `run_policy_decision` from the policy module, and `trace` builders;
  - implements the control flow from the spec;
  - after each stage, `yield {"type": "stage", "step_name": NAME, "state_delta": stage_state_delta(...)}`;
  - on a stop, build `PipelineTrace`, then `yield {"type": "final", "state_delta": final_state_delta(trace), "trace": trace.model_dump()}` and `return`;
  - policy stage wraps `run_policy_decision` in try/except → `MANUAL_REVIEW` on error;
  - signature: `async def run_claim_pipeline(claim_input: dict, documents: list[dict]) -> AsyncIterator[dict]` where each `documents` item has `file_id, file_name, document_text`.
  - `claim_input` provides `claim_category, member_id, policy_id, treatment_date, claimed_amount, has_pre_authorization, relationship_claim_type, patient_member_id, claims_history` (mirrors today's metadata) for the policy call.

- [ ] **Step 4: Run → passes** (`uv run pytest tests/test_orchestrator.py -q`).
- [ ] **Step 5: Commit** — `feat(pipeline): add deterministic claim orchestrator state machine`

---

### Task 5: Rewire `main.py` to the orchestrator

**Files:** Modify `api/main.py`; Create `api/tests/test_main_pipeline.py`

- [ ] **Step 1: Failing test** — assert the events from `run_claim_pipeline` are serialized to SSE and the final trace is captured for write-back. Test a small helper `pipeline_event_to_sse(event, claim_id, user_id, session_id)` (extracted in main) → returns dict with `actions.state_delta == event["state_delta"]` and the ids attached.

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement**
  - Add import: `from pipeline.orchestrator import run_claim_pipeline`.
  - Replace the post-OCR block (`build_agent_content` + `runner` setup + `runner.run_async` loop + the final `pipeline_trace` extraction) with:
    ```python
    documents_with_text = [
        {"file_id": d["file_id"], "file_name": d["file_name"],
         "document_text": text_by_id.get(d["file_id"], "")}
        for d in documents
    ]
    claim_pipeline_input = {**claim_input, "claim_id": claim_id,
                            "claims_history": claim.get("claims_history", [])}
    final_trace = None
    async for ev in run_claim_pipeline(claim_pipeline_input, documents_with_text):
        sse = pipeline_event_to_sse(ev, claim_id, user_id, session_id)
        yield f"data: {json.dumps(sse)}\n\n"
        if ev["type"] == "final":
            final_trace = ev["trace"]
    # write-back (same as before)
    final_status = (final_trace or {}).get("final_status")
    await db.update_claim_final(claim_id, final_status, final_trace)
    if final_status in ("APPROVED", "PARTIAL"):
        await db.db_mark_claim_approved(claim_id)
    ```
  - Add `pipeline_event_to_sse(...)` helper near `ocr_step_event`.
  - Remove `_start_session`, `Runner`/`InMemorySessionService`/`InMemoryArtifactService` usage, `_is_partial_tool_only_event`, `_flatten_pipeline_trace_state_delta`, and the `from agents.agent import root_agent` import. Keep `build_agent_content`? No — remove it (no agent Content anymore); keep `ocr_step_event`. Keep the privacy-invariant target: there is now simply no image path at all.
  - Update `api/tests/test_prestage_wiring.py` and `api/tests/test_privacy_invariant.py`: remove references to `build_agent_content` (deleted). Replace the privacy test with one asserting `documents_with_text` items contain only text keys (no `bytes`).

- [ ] **Step 4: Run full suite** (`uv run pytest -q`) → green.
- [ ] **Step 5: Commit** — `feat(pipeline): drive claim_events via deterministic orchestrator; remove ADK runner`

---

### Task 6: Remove the root agent + ADK from the request path

**Files:** Delete `api/agents/agent.py`; Modify the four `api/agents/*/agent.py`

- [ ] **Step 1:** Delete `api/agents/agent.py` (root orchestrator — its `PipelineTrace`/`PipelineStepResult` now live in `pipeline/trace.py`).

- [ ] **Step 2:** In each of `document_gate_agent`, `document_requirements_agent`, `document_extraction_agent`, `consistency_check_agent`: remove the `from google.adk... import LlmAgent` / `GenerateContentConfig` imports and the trailing `<name> = LlmAgent(...)` instantiation. Keep the `PROMPT` constant and all Pydantic models. Leave `MODEL` constant (harmless) or remove.

- [ ] **Step 3:** Grep for stragglers:
```
grep -rn "from agents.agent\|root_agent\|AgentTool\|LlmAgent\|google.adk" api/ --include=*.py
```
Expected: no remaining references in the request path (`main.py`, `pipeline/`, `agents/*/agent.py`).

- [ ] **Step 4:** `uv run python -c "import main"` imports clean; `uv run pytest -q` green.

- [ ] **Step 5: Commit** — `refactor: remove LLM root orchestrator and ADK from the request path`

---

### Task 7: Verify + optional dependency cleanup

- [ ] **Step 1:** Full suite green: `cd api && uv run pytest -q`.
- [ ] **Step 2:** App boots: `DATABASE_URL=... GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_PROJECT=... uv run python -c "import main; print('ok')"`.
- [ ] **Step 3 (optional):** If `grep -rn "google.adk" api --include=*.py` is empty, remove `google-adk` from `pyproject.toml`/`requirements.txt` and `uv sync`. If anything still imports it, skip this step.
- [ ] **Step 4: Commit** — `chore(pipeline): verify suite; drop unused google-adk dependency` (only if step 3 applied).

---

## Self-Review

**Spec coverage:** deterministic orchestrator (T4), Approach-A genai call-site (T1), reused prompts/schemas (T3), pure-Python policy unchanged (T4 uses `run_policy_decision`), zero-UI SSE shapes (T2/T5), ADK removed (T6), model abstraction one-file (T1), testing incl. branch coverage (T4) — all mapped. ✓

**Placeholder scan:** Stage prompts/schemas are imported, not re-pasted (DRY, and they're large existing assets) — acceptable; all new code shown in full. The one runtime-verify note (ConsistencyCheckResult error-path fields) is explicit. ✓

**Type consistency:** `structured_llm_call(system_prompt, payload, output_model, *, model, client)`, stage fns return their existing result models, `build_consistency_snapshots(list[DocumentExtractionResult]) -> list[DocumentConsistencySnapshot]`, orchestrator yields `{"type","step_name?","state_delta","trace?"}`, `run_claim_pipeline(claim_input, documents)` — consistent across tasks. ✓

---

## Execution Handoff
Inline execution via executing-plans (chosen by user: "write and execute").
