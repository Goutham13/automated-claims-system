# Deterministic Python Orchestrator — Design

**Date:** 2026-06-07
**Status:** Approved design, pending implementation plan
**Milestone:** #1 of the production-grade migration (orchestration foundation). Temporal/durable
execution is explicitly deferred to a later milestone; confidence-band routing and DMN
decisioning are separate later milestones.

---

## Motivation

The root orchestrator is currently an LLM (`gemini-2.5-pro`) asked to follow a ~200-line prompt
that is, in effect, a fixed state machine ([api/agents/agent.py](../../../api/agents/agent.py)).
This is the wrong tool for the job:

- **Non-determinism where we least want it.** Claims adjudication is a known, auditable, fixed
  sequence. Control flow belongs in code, not in an LLM's instruction-following.
- **Reliability.** The LLM orchestrator is the hardest component to self-host and the most
  failure-prone (it also produced the Vertex/ADK nested-schema crash when building the
  `PipelineTrace` function declaration).
- **Untestable.** Orchestration logic living in a prompt cannot be unit-tested.

Market research (durable-execution engines, IDP platforms, DMN rules engines, incumbent insurer
platforms) confirms the production pattern: a **deterministic spine** with **LLMs as bounded
understanding steps** and **deterministic decisioning**. This milestone moves the spine into code.

Principle preserved and reinforced: **LLMs for understanding, Python for decisions.**

---

## Goals

- Replace the LLM root orchestrator with a deterministic Python pipeline.
- The LLM is invoked only for the four scoped *understanding* tasks (classify, requirements,
  extract, consistency).
- Reuse the existing, well-tuned sub-agent **prompts and Pydantic schemas**.
- Keep `run_policy_decision` (pure Python) unchanged — the money stays deterministic.
- Zero frontend changes: SSE event shapes and DB write-back stay identical.
- One model call-site, to set up the future self-hosting (Qwen/LiteLLM) milestone.

## Non-Goals (this milestone)

- Temporal / durable execution (crash-safety, HITL pause/resume). **Deferred.**
- Confidence-band routing / straight-through-processing / exception-queue UI. **Later milestone.**
- DMN / rules-engine decisioning. **Later milestone.**
- Self-hosting the understanding models. **Later milestone** (this design makes it a one-file change).

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Orchestration | **Deterministic Python state machine** | Auditable, testable, reliable; flow is fixed. |
| Stage model invocation | **Direct `google-genai` controlled generation** (Approach A) | Reuses prompts/schemas, drops the ADK agent/tool layer, gives one swap point for self-hosting; sidesteps the ADK nested-schema crash. |
| ADK in request path | **Removed** | Sub-agent modules refactored to export `PROMPT` + schemas; `LlmAgent` objects dropped. `google-adk` dep can be removed once unused. |
| Policy decision | **Unchanged** (pure Python) | The money must stay deterministic and auditable. |
| Trace / SSE | **Python-emitted, same shapes** | Zero UI changes; deterministic event ordering. |
| Orchestrator model | **No `pro`** — stages use `gemini-3-flash-preview` | No orchestrator LLM remains; stages are scoped. |

---

## Architecture

### What goes
- `api/agents/agent.py` root agent: `ROOT_PIPELINE_PROMPT`, the `PipelineTrace` output-schema on
  the LLM, the `AgentTool` wrappers, and `runner.run_async(root_agent)` in `main.py`.
- `main.py` ADK-specific helpers `_is_partial_tool_only_event` and
  `_flatten_pipeline_trace_state_delta` (no longer needed).

### What stays (reused)
- The four sub-agent **prompts and Pydantic schemas** (the asset).
- `run_policy_decision` + `PolicyDecision` (pure Python), unchanged.
- The OCR pre-stage, the per-stage SSE event pattern, the DB write-back, the privacy invariant.

### New package — `api/pipeline/`
```
api/pipeline/
├── __init__.py
├── orchestrator.py   # run_claim_pipeline(): the explicit state machine (async generator)
├── stages.py         # classify_document / check_requirements / extract_document /
│                     #   check_consistency / build_consistency_snapshots
├── llm.py            # structured_llm_call(system_prompt, payload, output_model) — ONE call site
└── trace.py          # PipelineTrace / PipelineStepResult + per-stage SSE event builders
```

### Sub-agent module refactor
Each of `document_gate_agent`, `document_requirements_agent`, `document_extraction_agent`,
`consistency_check_agent` is refactored to export its `PROMPT` constant and its input/output
Pydantic models, and to **drop the `LlmAgent` object**. This removes ADK from the request path.

---

## Control Flow (ported from `ROOT_PIPELINE_PROMPT`)

`run_claim_pipeline(claim_input, documents_with_text)` — async generator, yields a stage event
after each step, returns the final `PipelineTrace`:

```
1. DOCUMENT_CLASSIFICATION
     for each doc: classify_document(file_id, file_name, document_text)
     if ANY gate_outcome == "PENDING_REUPLOAD":
          final_status = PENDING_MEMBER_ACTION; STOP
2. DOCUMENT_REQUIREMENTS
     predicted_types = [r.predicted_type for r in classifications]
     req = check_requirements(claim_category, predicted_types)
     if req.outcome == "BLOCKED":          final_status = STOPPED_AT_GATE;        STOP
     if req.outcome == "PENDING_REUPLOAD": final_status = PENDING_MEMBER_ACTION;  STOP
3. DOCUMENT_EXTRACTION
     for each gate-passed doc: extract_document(file_id, file_name, document_type, document_text)
4. CONSISTENCY_CHECK
     snapshots = build_consistency_snapshots(extraction_results)   # deterministic field mapping
     cons = check_consistency(snapshots)
     if cons.outcome == "BLOCKED":                  final_status = STOPPED_AT_CONSISTENCY; STOP
     if cons.outcome == "MANUAL_REVIEW_RECOMMENDED": warnings += [...]; continue
5. POLICY_DECISION
     decision = run_policy_decision(...)            # pure Python, unchanged
     final_status = decision.decision               # APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW
     on unexpected exception:                       final_status = MANUAL_REVIEW
```

Two things that were fragile inside the LLM prompt become exact in Python:
- **`build_consistency_snapshots`** — the "first non-null of …" field mapping
  (`agent.py:137-153`) becomes deterministic code.
- **Stop/continue conditions** — real branches with real test coverage.

---

## Module Responsibilities

### `llm.py`
```python
def structured_llm_call(system_prompt: str, payload: BaseModel | dict, output_model: type[T]) -> T:
    # google-genai Vertex client:
    #   config = GenerateContentConfig(response_mime_type="application/json",
    #                                  response_schema=output_model, temperature=0.1)
    # contents = system_prompt + serialized payload
    # returns output_model parsed from response (response.parsed or json.loads(response.text))
```
- The single place the model is called. Model id per call from config (default
  `gemini-3-flash-preview`). Future self-hosting = change here only.

### `stages.py`
- `classify_document(doc) -> DocumentClassificationResult` (reuses gate PROMPT + schema)
- `check_requirements(claim_category, predicted_types) -> DocumentRequirementsResult`
- `extract_document(doc) -> DocumentExtractionResult`
- `check_consistency(snapshots) -> ConsistencyCheckResult`
- `build_consistency_snapshots(extraction_results) -> list[DocumentConsistencySnapshot]` (pure)

### `orchestrator.py`
- `run_claim_pipeline(...)` async generator implementing the control flow above.

### `trace.py`
- `PipelineTrace` / `PipelineStepResult` models (moved from `agent.py`).
- `stage_event(step_name, status, summary, key_findings, ...)` and `final_event(trace)` builders
  that produce SSE payloads in the existing UI shape.

---

## Trace / UI Compatibility

- The UI renders any `actions.state_delta` key with a `status` field as a trace step
  ([ui/src/context/ClaimsContext.tsx:258](../../../ui/src/context/ClaimsContext.tsx#L258)).
  The orchestrator emits one such event per stage (`DOCUMENT_CLASSIFICATION`,
  `DOCUMENT_REQUIREMENTS`, `DOCUMENT_EXTRACTION`, `CONSISTENCY_CHECK`, `POLICY_DECISION`) —
  identical to the existing `ocr_step_event` pattern.
- The final event carries the same keys produced today: `final_status`, `final_member_message`,
  `final_ops_summary`, `blockers`, `warnings`, `policy_decision`.
- **Result: zero frontend changes.**

### `main.py` changes
- After the OCR pre-stage, replace the `Content` build + `runner.run_async(root_agent)` block with:
  `async for event in run_claim_pipeline(claim_input, documents_with_text): yield SSE(event)`.
- Keep the existing DB write-back (`update_claim_final`, `db_mark_claim_approved` on
  `APPROVED`/`PARTIAL`).
- Remove `_is_partial_tool_only_event` and `_flatten_pipeline_trace_state_delta`.

---

## Error Handling

| Failure | Behavior |
|---|---|
| A stage LLM call errors / returns invalid JSON | Caught in the stage; treated as that stage failing → mapped to the stage's stop status (e.g. classification error → that file `PENDING_REUPLOAD`); orchestrator records it in the trace. |
| `run_policy_decision` raises | `final_status = MANUAL_REVIEW`, error detail in the step summary/ops summary (mirrors current `agent.py:190-193`). |
| Any unexpected orchestrator exception | Caught at the `main.py` boundary → SSE error event + `MANUAL_REVIEW`, as today. |

---

## Testing

- **Orchestrator branch tests** (mock `stages.py`): each stop/continue path →
  - gate `PENDING_REUPLOAD` → `PENDING_MEMBER_ACTION`
  - requirements `BLOCKED` → `STOPPED_AT_GATE`
  - requirements `PENDING_REUPLOAD` → `PENDING_MEMBER_ACTION`
  - consistency `BLOCKED` → `STOPPED_AT_CONSISTENCY`
  - consistency `MANUAL_REVIEW_RECOMMENDED` → warning + continue to decision
  - decision passthrough (`APPROVED`/`PARTIAL`/`REJECTED`/`MANUAL_REVIEW`)
  - decision exception → `MANUAL_REVIEW`
- `build_consistency_snapshots` unit test (field-mapping correctness across document types).
- `llm.py` test (mock genai client: `response_schema` wired; parses to model instance).
- `stages.py` tests (mock `structured_llm_call`: prompt/schema wiring per stage).
- Happy-path integration test of `run_claim_pipeline` (all stages mocked → `APPROVED` trace +
  correct event sequence).
- Existing OCR + privacy-invariant tests stay green.

This milestone makes the orchestration logic fully unit-testable for the first time.

---

## Future Work (out of scope here)

- **Temporal / durable execution** — wrap `run_claim_pipeline` for crash-safety, retries, and
  human-in-the-loop pause/resume (milestone #1b).
- **Confidence-band routing + STP + exception queues** (milestone #2).
- **DMN / rules-engine decisioning** for explainable, analyst-editable adjudication (milestone #3).
- **Self-hosting the understanding models** (Qwen via `llm.py`) — one-file change enabled by this design.
