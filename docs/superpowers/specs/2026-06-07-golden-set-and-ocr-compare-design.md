# Golden-Set Reference + OCR Comparison — Design

**Date:** 2026-06-07
**Status:** Approved design, pending implementation
**Extends:** the eval harness (`api/evals/`).

Two deliverables:
1. **Golden-set refactor** — capture the Gemini reference **once**, reuse it for all candidates
   (instead of recomputing the reference on every candidate run).
2. **OCR comparison (separate task)** — VLM OCR vs Gemini-3-pro OCR, text-similarity.

---

## Part 1 — Golden-set reference

### Problem
`stage_compare` currently runs the reference model live on every candidate run, so the (slow,
costly) Gemini-pro reference is recomputed N times. The reference outputs don't change between
candidates, and re-sampling at temperature adds noise.

### Design
Capture the reference **once** and commit it; candidates compare against the cached gold.

- Reference model: **`gemini-3-pro-preview`** (configurable via `REF_MODEL`).
- Reference is only needed for the **label-less** stages (extraction, consistency). Classification &
  requirements are scored vs **true labels** (`actual_type` / computed rule), so the reference's role
  there is just an optional "pro column" (its own accuracy vs truth), captured once too.

**Pro calls:** ~36 once (24 extraction + 12 consistency) + optional 36 (24 classification + 12
requirements) for pro's own accuracy — versus ~144 if recomputed across 4 candidates.

### Reference store
`evals/reference/<case_id>.json` (committed), one file per case:
```json
{
  "classification": {"<file_id>": {DocumentClassificationResult}},
  "requirements": {DocumentRequirementsResult},
  "extraction": {"<file_id>": {DocumentExtractionResult}},
  "consistency": {ConsistencyCheckResult},
  "ref_model": "gemini-3-pro-preview"
}
```

### Components
- **`evals/capture_reference.py`** (`python -m evals.capture_reference`): runs the reference model
  (gemini, `REF_MODEL`) over all cases using the OCR fixtures + ground-truth `actual_type`, and writes
  the per-case reference JSON. Idempotent. Mirrors `capture.py`.
- **`evals/reference.py`**: `load_reference() -> dict[case_id, RefCase]` (parsed back into the
  Pydantic result models).
- **Refactored dimensions** (`scorer.py`):
  - `ExtractionAgreementDimension(cand)` — reads cached pro extraction per doc; runs candidate
    extraction; field-agreement vs cached. (Constructor drops the `ref` model; takes only `cand`.)
  - `ConsistencyAgreementDimension(cand)` — builds snapshots from cached pro extraction (fixed input);
    runs candidate consistency; outcome-agreement vs cached pro consistency.
- **Refactored `stage_compare.py`**: loads the reference store + pro's cached cls/req metrics; runs the
  candidate's classification/requirements (vs truth) + extraction/consistency (vs cached gold);
  emits one report. Candidate runs once; no live reference calls.

### Backward-compat
The agreement-dimension constructor signatures change (`ref, cand` → `cand`); their tests update.
Classification/requirements dimensions unchanged. Production pipeline untouched.

### Run
```bash
# 1. Golden set, once (Vertex; pro)
REF_MODEL=gemini-3-pro-preview python -m evals.capture_reference

# 2. Each candidate vs cached gold (cheap, reproducible)
PIPELINE_BACKEND=gemini PIPELINE_MODEL=gemini-3-flash-preview python -m evals.stage_compare
PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:7b-instruct     python -m evals.stage_compare
PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:14b            python -m evals.stage_compare
PIPELINE_BACKEND=ollama PIPELINE_MODEL=llama3.1:8b           python -m evals.stage_compare
```
Then assemble a 4-candidate × 4-stage table (+ latency) into `evals/README.md`.

---

## Part 2 — OCR comparison (separate task)

### Goal
Compare the self-hosted **VLM OCR** (`qwen2.5vl-ocr`) against **Gemini-3-pro OCR** on the 12 cases'
document images. No gold transcription exists → metric is **text similarity** (treat pro OCR as the
stronger reference; report VLM agreement).

### Components
- **`evals/ocr_reference.py`** (`python -m evals.ocr_reference`): runs gemini-3-pro multimodal OCR on
  each document image (image part + transcribe prompt, plain text out), writes
  `evals/reference_ocr/<case_id>/<file_id>.txt` (committed). This is a new genai *multimodal* call
  (not the text structured path).
- **`evals/ocr_compare.py`** (`python -m evals.ocr_compare`): for each doc, load the committed VLM OCR
  fixture (`evals/fixtures/...`) and the pro OCR text; compute similarity:
  - `difflib.SequenceMatcher(None, a, b).ratio()` on normalized text (lowercased, whitespace-collapsed),
  - plus token-level Jaccard, and char-count delta.
  Aggregate mean similarity; list the most-divergent docs. Write a report + print markdown.

### Honesty note
This measures VLM-vs-pro **agreement**, not absolute OCR accuracy (no gold text). It answers "how
close is the local VLM OCR to a frontier model's OCR," which is the practical question for trusting
the self-hosted OCR.

---

## Testing
- `reference.py` load round-trips a written reference file into the result models.
- Refactored `ExtractionAgreementDimension` / `ConsistencyAgreementDimension`: monkeypatch the
  candidate stage fns + a fake cached reference → correct agreement math.
- `ocr_compare` similarity helper: identical text → 1.0; disjoint → low; normalization works.
- No live model calls in tests; captures (reference, ocr_reference) and the candidate/OCR runs are manual.

## Non-Goals
- Gold transcriptions / absolute OCR accuracy (agreement-vs-pro is the metric).
- Changing the production default backend or OCR model.
