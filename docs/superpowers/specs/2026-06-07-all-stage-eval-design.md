# All-Stage Eval Comparison (instruct vs gemini) — Design

**Date:** 2026-06-07
**Status:** Approved design, pending implementation plan
**Extends:** the classification-first eval harness (`api/evals/`). Adds per-stage comparison across
all four understanding stages, head-to-head **`qwen2.5:7b-instruct` (ollama)** vs **`gemini`**.
The VLM is OCR-only and excluded.

---

## Motivation

The harness scores only **classification** today. To decide whether the self-hosted text model can
replace Gemini across the whole pipeline, we need a per-stage comparison for **requirements,
extraction, and consistency** too. Label availability differs by stage, so the metric differs:

| Stage | Label source | Metric |
|---|---|---|
| Classification | `actual_type` (gold) | accuracy of each model vs truth |
| Requirements | **computed** from the documented rules | accuracy of each model vs computed outcome |
| Extraction | none → **Gemini as reference** | field-agreement % (instruct vs Gemini) + critical-field completeness |
| Consistency | none → **Gemini as reference** | outcome-agreement % (instruct vs Gemini) |

Extraction/consistency are **agreement (divergence)** metrics, not accuracy — there is no gold label.

---

## Stage isolation (fixed inputs)

Each stage is measured on its own, independent of upstream model errors:
- **Classification:** OCR fixture text.
- **Requirements:** `claim_category` + **ground-truth `actual_types`** (not the classifier's output).
- **Extraction:** `document_type = actual_type` + OCR fixture text.
- **Consistency:** snapshots built from **Gemini's** extraction output (identical input fed to both
  models' consistency calls).

---

## Requirements rules (encoded deterministically)

From `DOCUMENT_REQUIREMENTS_PROMPT`:

| claim_category | required types |
|---|---|
| CONSULTATION | PRESCRIPTION, HOSPITAL_BILL |
| DIAGNOSTIC | PRESCRIPTION, LAB_REPORT, HOSPITAL_BILL |
| PHARMACY | PRESCRIPTION, PHARMACY_BILL |
| DENTAL | HOSPITAL_BILL |
| VISION | PRESCRIPTION, HOSPITAL_BILL |
| ALTERNATIVE_MEDICINE | PRESCRIPTION, HOSPITAL_BILL |

`_expected_requirements(claim_category, actual_types)` → `PASS` if required ⊆ present, else
`NOT_PASS`. Scoring normalizes the model's outcome to `PASS` vs not-`PASS` (so `PENDING_REUPLOAD`
and `BLOCKED` both count as "not satisfied" — the meaningful requirements decision). Raw outcome is
also recorded.

---

## Code changes

### 1. Thread backend/model through (backward-compatible)
Add optional `backend: str | None = None, model: str | None = None` to:
- `pipeline.llm.structured_llm_call` — when `backend` given, use it; else read env.
- the four `pipeline.stages` functions (`classify_document`, `check_requirements`,
  `extract_document`, `check_consistency`) — pass through to `structured_llm_call`.

Defaults preserve current behavior (env-driven), so `orchestrator.py` / `main.py` are untouched.
This lets one process call both Gemini and the candidate.

### 2. New scorer dimensions (`evals/scorer.py`)
- `RequirementsDimension(model_a, model_b)` — runs `check_requirements` for both models on the
  ground-truth `actual_types`; scores each vs `_expected_requirements`.
- `ExtractionAgreementDimension(ref, cand)` — runs `extract_document` for both; for each doc, flattens
  the populated typed section (the `*Fields` submodel matching `document_type`) and computes
  field-agreement (`matching_fields / total_fields`, `None==None` counts as match). Aggregates mean
  field-agreement + per-model critical-field completeness (% of `missing_critical_fields == []`).
- `ConsistencyAgreementDimension(ref, cand)` — builds snapshots from `ref`'s extraction; runs
  `check_consistency` for both on those snapshots; outcome-agreement = match rate of `outcome`.

Each dimension records per-model latency.

### 3. New command (`evals/stage_compare.py`)
`python -m evals.stage_compare` — reference = Gemini, candidate = env
(`PIPELINE_BACKEND`/`PIPELINE_MODEL`, default ollama `qwen2.5:7b-instruct`):
- runs all four dimensions, prints one per-stage table (accuracy for labeled stages; agreement % for
  extraction/consistency; latency per stage per model), and writes a JSON + markdown report to
  `results/stage_compare_<timestamp>.json`.
- `ref` model/backend default: `gemini` / `gemini-3-flash-preview`; candidate via env.

---

## Testing

- `_expected_requirements`: rule table correctness (PASS when satisfied; NOT_PASS when a required
  type is missing) across categories.
- `RequirementsDimension`: monkeypatched `check_requirements` → correct per-model accuracy.
- `ExtractionAgreementDimension`: monkeypatched `extract_document` returning two `DocumentExtractionResult`s
  → correct field-agreement math (full match = 1.0; one differing field < 1.0); completeness.
- `ConsistencyAgreementDimension`: monkeypatched `extract_document` + `check_consistency` → outcome
  agreement 1.0 when equal, 0.0 when differing.
- `structured_llm_call` / stage functions honour an explicit `backend`/`model` arg (dispatch test).
- No live model calls in tests. The actual instruct-vs-gemini run is manual (needs Ollama + Vertex).

---

## Deliverable

A committed `stage_compare` report (instruct vs gemini across all four stages, accuracy + agreement +
latency) and a short summary appended to `evals/README.md`. Default backend stays `gemini`.

## Non-Goals

- Gold labels for extraction/consistency (agreement-vs-Gemini is the chosen metric).
- End-to-end (chained) scoring — stages are isolated by design.
- Changing the production default backend.
