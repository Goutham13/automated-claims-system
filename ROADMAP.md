# Project Roadmap & Context

> **For a new Claude session:** read this file first. It captures what the system is, what was
> built, the key decisions/findings, and the scoped next steps. Detailed design docs and plans live
> in `docs/superpowers/specs/` and `docs/superpowers/plans/`.

---

## 1. What this project is

**Plum Health Insurance Claims Processing** — an AI pipeline that adjudicates health-insurance
claims from uploaded documents (prescriptions, bills, lab reports) to a final
`APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW` decision.

**Core principle: _LLMs for understanding, Python for decisions._** LLMs read/classify/extract from
messy documents; deterministic Python computes every financial decision with a full audit trail.

Stack: FastAPI + Python 3.11 (`api/`), React/TanStack UI (`ui/`), Postgres, Ollama for self-hosted
models. Package manager: `uv` (api), `npm` (ui).

---

## 2. Current architecture (after this session)

```
POST /claims  →  intake stored in Postgres (document bytes + metadata)
GET /claims/{id}/events  (SSE stream)
        │
        ▼
OCR PRE-STAGE  (api/ocr/)  — self-hosted Qwen-VL via Ollama; PDF→PNG rasterize → text
        │   (images go ONLY to the local VLM; never to any external API)
        ▼
DETERMINISTIC PYTHON ORCHESTRATOR  (api/pipeline/orchestrator.py)
   explicit state machine — NO LLM orchestrator, ADK removed from the request path
   ├─ classify        → pipeline/stages.classify_document
   ├─ requirements    → pipeline/stages.check_requirements   (still an LLM call today)
   ├─ extraction      → pipeline/stages.extract_document
   ├─ consistency     → pipeline/stages.check_consistency
   │     all via pipeline/llm.structured_llm_call (backend = gemini | ollama)
   └─ policy decision → agents/policy_decision_agent.run_policy_decision  (PURE PYTHON)
        │
        ▼
SSE events streamed to UI; final PipelineTrace written back to DB
```

### Key files
| Area | Path |
|---|---|
| OCR pre-stage | `api/ocr/{rasterize,client,service}.py` |
| Pipeline | `api/pipeline/{orchestrator,stages,llm,trace}.py` |
| Stage prompts + Pydantic schemas | `api/agents/<stage>_agent/agent.py` (LlmAgent objects removed; only `*_PROMPT` + schemas remain) |
| Policy engine (pure Python) | `api/agents/policy_decision_agent/agent.py` (`run_policy_decision`) |
| API entrypoint + SSE | `api/main.py` (`claim_events`, `ocr_step_event`, `pipeline_event_to_sse`, `build_documents_with_text`) |
| Eval harness | `api/evals/` (see §5) |
| UI event handling | `ui/src/context/ClaimsContext.tsx`, `ui/src/lib/claims-types.ts`, `ui/src/components/claims/PipelineProgress.tsx` |

### Model backends (`api/pipeline/llm.py`)
`structured_llm_call(...)` dispatches on `PIPELINE_BACKEND`:
- `gemini` (current default) — google-genai controlled generation (Vertex). **To be removed (see §6).**
- `ollama` — OpenAI-compatible endpoint; `response_format: json_object` + Pydantic-validate + 1 retry.
- Per-call `backend`/`model` overrides exist (used by the eval harness).

Self-hosted models (Ollama): `qwen2.5vl-ocr` (OCR, 8192 ctx) and the chosen stage model.

---

## 3. What was achieved this session

All merged to `main` (PRs #1–#3).

1. **Self-hosted OCR pre-stage** — images OCR'd by a local Qwen-VL (Ollama); the orchestrator and
   all stages receive text only. First step of "no PHI to external APIs."
2. **Deterministic Python orchestrator** — replaced the LLM root orchestrator (and removed Google
   ADK from the request path). Control flow is now explicit, fully unit-tested Python. The previous
   agentic version is preserved on branch `approach/agentic-orchestrator` (tag `agentic-orchestrator`).
3. **Eval harness** (`api/evals/`) — classification-first, then extended to:
   - **Golden-set reference** captured once (`evals/reference/`, via `gemini-2.5-pro`); candidates
     compare against the cache (deterministic, ~4× fewer reference calls).
   - **All-stage comparison** (`stage_compare.py`): classification/requirements vs labels;
     extraction/consistency = agreement vs golden set; per-stage latency.
   - **Fair, type-aware extraction scoring** (`field_compare.py`): dates/numbers/case/list-order no
     longer count as mismatches; reports field-agreement, exact-only, **critical-field** agreement.
   - **OCR comparison** (`ocr_compare.py`) vs a **Claude Opus 4.8** hand-transcribed golden set
     (`evals/reference_ocr/`) — created because the Gemini API billing was cut.

**Test status:** `cd api && uv run pytest -q` → all green (68 tests at session end).

---

## 4. Key findings & decisions

- **OCR is solved.** Self-hosted VLM OCR vs Claude Opus 4.8: **mean token-Jaccard 95.6%** (~100% on
  23/24 clean docs). Only the intentionally-blurry bill diverges (correctly gated to
  `PENDING_REUPLOAD`). OCR is **not** the self-hosting bottleneck.
- **Extraction is the residual gap** vs Gemini for self-hosting. Fair-scored critical-field agreement:
  | Model | Classif | Requirements | Extraction (critical) | Consistency |
  |---|---|---|---|---|
  | gemini-3-flash | 95.8% | 100% | 100% | 91.7% |
  | qwen2.5:7b | 91.7% | 91.7% | 79.2% | 100% |
  | **qwen2.5:14b** | 87.5% | 100% | **87.5%** | 100% |
  | llama3.1:8b | 95.8% | 8.3% | 51.4% | 8.3% (unsuitable) |
- **Decision: standardize on `qwen2.5:14b` for all LLM stages** (incl. extraction). No further model
  comparison/eval needed for the next phase — the work is prompting + latency on this fixed model.
- **`requirements` is deterministic rules** (`evals/scorer._expected_requirements` /
  `_REQUIRED`) → it should become pure Python, removing an LLM call.
- Reference/golden sets are committed, so eval re-runs need no API. The API-based capture scripts
  (`capture_reference.py`, `ocr_reference.py`) are retained but will be non-runnable once the API is
  removed (the committed golden sets remain valid).

---

## 5. Eval harness reference (`api/evals/`)

| File | Purpose |
|---|---|
| `dataset.py` | Load `test_cases.json` + mock docs + OCR fixtures → `EvalCase[]` |
| `capture.py` | Capture VLM OCR text → `evals/fixtures/` (committed) |
| `scorer.py` | Dimensions: Classification, Requirements, Extraction/Consistency agreement (+ `field_compare`) |
| `field_compare.py` | Type-aware value comparison (exact/normalized/mismatch) |
| `report.py`, `run.py` | Result/markdown/baseline + classification CLI |
| `stage_compare.py` | All-stage candidate-vs-golden-set comparison CLI |
| `reference/` | `gemini-2.5-pro` stage golden set (committed) |
| `reference_ocr/` | Claude Opus 4.8 OCR golden set (committed) |
| `capture_reference.py`, `ocr_reference.py` | API-based golden-set capture (retained; needs API) |

Run a comparison: `cd api && PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:14b uv run python -m evals.stage_compare`

---

## 6. NEXT STEPS (scoped)

### A. Go fully self-hosted — remove all external LLM API calls ⭐
- Make **Ollama the only/default backend**: `PIPELINE_BACKEND=ollama`,
  `PIPELINE_MODEL=qwen2.5:14b`; OCR stays `qwen2.5vl-ocr`.
- **Remove the Gemini backend** (`_gemini_call`) from `pipeline/llm.py` and the `google-genai`
  import there.
- **Remove the last ADK usage**: the Cloud Trace telemetry imports in `main.py`
  (`google.adk.telemetry...`).
- **Drop `google-adk` and `google-genai`** from `api/pyproject.toml` / `api/requirements.txt`.
- Result: **no external LLM API anywhere** in the request path. (No production GPU hosting for now —
  runs against local Ollama.)

### B. Extraction: prompting + latency (model fixed at `qwen2.5:14b`)
- **Do NOT change the model.** Improve extraction **prompting** to raise critical-field accuracy.
- **Reduce latency** (14B was ~54 s/doc on the M4): tune `num_ctx`, output size, `keep_alive`,
  consider per-stage prompt trimming — without switching models.
- No new eval/quality work required to proceed; use existing `stage_compare` only if helpful.

### C. Requirements stage → deterministic Python
- Replace the `check_requirements` LLM call with pure Python using the documented rules
  (`_REQUIRED` map already exists). Removes one LLM call and is 100% reliable.

### D. Simplify the custom SSE events + update UI and API
- ADK is fully removed, so the SSE events no longer need to mimic ADK's
  `actions.state_delta` shape. **Design a clean custom event schema** (e.g.
  `{type, step, status, summary, key_findings, final_status, ...}`).
- Update the **API** emitters in `main.py` (`ocr_step_event`, `pipeline_event_to_sse`, final/outage
  events) to the new schema.
- Update the **UI** consumers (`ui/src/context/ClaimsContext.tsx` step/heuristic parsing,
  `ui/src/lib/claims-types.ts`, `ui/src/components/claims/PipelineProgress.tsx`) to match.
- Goal: simpler, self-documenting events; drop the ADK-era `state_delta` nesting and any
  partial-tool-event handling remnants.

### E. Production-grade architecture (target shape; from market research)
The production pattern is a **deterministic spine + LLM understanding + deterministic decisions +
agentic edges**. Items (sequence as the system matures):
- **Durable execution (Temporal)** — wrap `run_claim_pipeline` for crash-safety, retries, and
  human-in-the-loop pause/resume.
- **Confidence-band routing + STP + exception queues** — route on the confidence scores the stages
  already emit (auto / review / manual); track straight-through-processing rate.
- **DMN / rules-engine decisioning** — evolve `run_policy_decision` toward explainable,
  analyst-editable decision tables with reason codes.
- **Fraud scoring** — as an *input* signal to the decision, never a decider.
- **Agentic edges** (later) — a conversational ops "claims copilot" for `MANUAL_REVIEW` cases;
  fraud investigation; appeals. Keep the deterministic spine for the happy path.

### F. Observability (not a priority, but tracked)
- The deterministic orchestrator dropped ADK's auto Cloud Trace spans. Add structured per-stage
  logging / OTel spans inside `run_claim_pipeline` so the pipeline trace doubles as an audit log.
  *(Lower priority than A–E.)*

### Explicitly OUT OF SCOPE for now
- Production GPU hosting of the models (local Ollama only for now).
- Eval/quality maturity (gold extraction labels, end-to-end decision eval, LLM-judge, CI eval gate).

---

## 7. How to run (local)

```bash
# Ollama (self-hosted models)
ollama serve                  # or open the Ollama app
ollama list                   # expect: qwen2.5vl-ocr, qwen2.5:14b

# Postgres
brew services start postgresql@16
createdb claims               # once

# API (api/.env: DATABASE_URL, OCR_MODEL=qwen2.5vl-ocr, PIPELINE_BACKEND=ollama, PIPELINE_MODEL=qwen2.5:14b)
cd api && uv sync && uv run uvicorn main:app --port 8000

# Tests
cd api && uv run pytest -q

# UI
cd ui && npm install && npm run dev
```

Login member IDs: `EMP001`–`EMP010`, `DEP001`/`DEP002` (password `member123`); valid claim
`member_id`s are in `policy_terms.json` (repo root).
