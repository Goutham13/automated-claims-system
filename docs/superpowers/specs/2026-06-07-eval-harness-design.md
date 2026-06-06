# Eval Harness (Classification-First) — Design

**Date:** 2026-06-07
**Status:** Approved design, pending implementation plan
**Milestone:** #2 of the production-grade migration. Prerequisite for safely self-hosting the
understanding-stage models (Gemini → Qwen) without quality regression.

---

## Motivation

The deterministic pipeline now calls the LLM only for scoped understanding stages through a single
swappable call-site (`pipeline/llm.py`). The next milestone is to self-host those stages (privacy
north star) — but we cannot swap models safely without a way to **measure stage quality and detect
regression**. Production claims systems treat per-stage evaluation as non-negotiable.

We have real ground truth in `test_cases.json` (12 cases) and matching inputs in
`mock_claim_documents/`. The labels best support **classification accuracy** (`documents[].actual_type`)
and end-to-end decisions (`expected.decision`). There is **no per-field extraction ground truth** and
no labeled consistency outcome today.

This milestone builds a **classification-first, stage-isolated** eval harness that produces a
reproducible quality baseline and a model-comparison (Gemini vs Qwen) workflow.

---

## Goals

- Score classification accuracy per document against `actual_type`, exactly and reproducibly.
- Make Gemini-vs-Qwen comparison a matter of changing `PIPELINE_MODEL` and re-running.
- Produce a saved, timestamped, model-tagged result + a baseline/compare workflow.
- Freeze stage *input* (captured OCR text fixtures) so comparisons are apples-to-apples.
- Structure scoring dimensions as pluggable, so extraction/consistency/decision/LLM-judge slot in
  later without restructuring.

## Non-Goals (v1)

- Extraction field-scoring and consistency scoring (need authored labels). **Deferred.**
- End-to-end decision/amount scoring. **Deferred.**
- LLM-judge for `system_must` / `rejection_reasons`. **Deferred.**
- CI integration (capture + live runs are manual/on-demand).

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Granularity | **Stage-isolated** | Isolates model quality per stage; ideal for model comparison. |
| v1 scope | **Classification only** | The only fully label-backed stage metric available today. |
| Stage input | **Captured OCR text fixtures (committed)** | Freezes input so only the model varies; later runs need no Ollama. |
| Build vs framework | **Lightweight in-house** | Scoring is exact-match + confusion; matches the composable/privacy ethos. |
| Model selection | **Via `PIPELINE_MODEL` env** (the existing call-site) | Comparison = change env + rerun; result records the model id. |
| Output | **JSON result + console/markdown report + baseline compare** | Reproducible baseline and regression diffing. |

---

## Architecture — `api/evals/`

```
api/evals/
├── __init__.py
├── dataset.py     # load test_cases.json + mock docs + captured fixtures → list[EvalCase]
├── capture.py     # one-time: run Qwen OCR over the 12 cases, save text fixtures
├── scorer.py      # Dimension interface + ClassificationDimension
├── report.py      # aggregate → result dict; render markdown; baseline compare
├── run.py         # CLI entry point
├── fixtures/      # committed OCR text per case   (TC001/F001.txt …)
└── results/       # timestamped run results + baseline.json
```

### Data model
```python
@dataclass
class EvalDocument:
    file_id: str
    file_name: str
    actual_type: str          # ground truth from test_cases.json
    ocr_text: str             # from captured fixture

@dataclass
class EvalCase:
    case_id: str
    case_name: str
    claim_category: str
    documents: list[EvalDocument]

@dataclass
class DimensionResult:
    name: str
    score: float                      # 0.0–1.0 aggregate
    details: dict[str, Any]           # per-item breakdown, confusion, etc.
```

### Dimension interface (pluggable)
```python
class Dimension(Protocol):
    name: str
    def score(self, cases: list[EvalCase]) -> DimensionResult: ...
```
v1 ships `ClassificationDimension`. Extraction/consistency/decision/LLM-judge dimensions are added
later by implementing this Protocol — no runner changes needed.

---

## Components

### `capture.py`
- `python -m evals.capture` (run from `api/`).
- For each test case, loads the case's documents from `mock_claim_documents/<case_id>/`, runs the
  OCR service (`ocr.service.extract_text_for_documents`, Qwen via Ollama), and writes the text to
  `evals/fixtures/<case_id>/<file_id>.txt`.
- Idempotent: re-running overwrites. Fixtures are committed so eval runs don't need Ollama.
- Maps `test_cases.json` documents to files on disk by `file_name`.

### `dataset.py`
- `load_cases() -> list[EvalCase]`: reads `test_cases.json`, joins each document with its captured
  fixture text and `actual_type`. Skips/﻿warns on missing fixtures.

### `scorer.py`
- `ClassificationDimension.score(cases)`:
  - For each document, call `pipeline.stages.classify_document({...ocr_text...})` (real stage → model).
  - Compare `predicted_type == actual_type`.
  - Aggregate: overall accuracy, per-type precision/recall, confusion matrix, and a
    "gate false-negative" count (real-typed doc sent to `PENDING_REUPLOAD`).
  - `details` carries the per-document rows (case_id, file_id, actual, predicted, correct, confidence).

### `report.py`
- `build_result(dimension_results, model_id) -> dict` with timestamp + model id.
- `render_markdown(result) -> str` — summary table + confusion matrix + failing rows.
- `compare(result, baseline) -> dict` — per-document regressions/improvements vs baseline.

### `run.py` (CLI)
- `python -m evals.run` → run dimensions, write `results/<timestamp>_<model>.json`, print markdown.
- `python -m evals.run --baseline` → also copy the run to `results/baseline.json`.
- `python -m evals.run --compare results/baseline.json` → print the diff.
- Records `PIPELINE_MODEL` (default `gemini-3-flash-preview`) in the result.

---

## Model comparison workflow

```
# Capture fixtures once (needs Ollama running)
python -m evals.capture

# Baseline on the current model (needs Vertex)
PIPELINE_MODEL=gemini-3-flash-preview python -m evals.run --baseline

# Later: self-hosted classifier, compare against baseline
PIPELINE_MODEL=<qwen-model> python -m evals.run --compare results/baseline.json
```

---

## Testing the harness

- `scorer` unit test: feed a tiny `list[EvalCase]` with a **monkeypatched `classify_document`**
  returning known predictions; assert accuracy, confusion, and gate-false-negative math.
- `dataset` unit test: a temp `test_cases.json` + temp fixtures → correct `EvalCase` join; missing
  fixture handled gracefully.
- `report` unit test: `compare()` correctly flags a regression and an improvement; markdown renders
  without error.
- No real model or OCR calls in tests. Capture + live runs are manual.

---

## Future Work (out of scope here)

- Extraction field-scoring & consistency dimensions (require authored ground-truth labels).
- End-to-end decision/amount dimension (needs Postgres + Vertex + Ollama).
- LLM-judge dimension for `system_must` / `rejection_reasons`.
- CI gate once a stable baseline and thresholds are agreed.
