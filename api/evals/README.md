# Eval Harness (classification-first)

Stage-isolated evaluation of the pipeline's understanding stages, so model swaps
(Gemini → self-hosted Qwen) can be made **without quality regression**.

v1 scores **classification accuracy** (`predicted_type` vs `actual_type` from
`test_cases.json`). Dimensions are pluggable — extraction / consistency / end-to-end /
LLM-judge can be added later via the `Dimension` protocol in `scorer.py`.

## How it works

1. **Capture OCR fixtures (once, needs Ollama):** runs the self-hosted OCR over the 12
   test cases and saves the extracted text to `fixtures/<case_id>/<file_id>.txt` (committed).
   Freezing the stage *input* makes model comparisons apples-to-apples.
2. **Run:** feeds each fixture's text to the real `classify_document` stage (which goes
   through `pipeline/llm.py` → whatever `PIPELINE_MODEL` is), and scores it.
3. **Baseline / compare:** save a run as `results/baseline.json`, then later diff a new run
   (e.g. Qwen) against it.

## Commands (run from `api/`)

```bash
# 1. Capture fixtures — Ollama must be serving the OCR model
set -a; source .env; set +a            # loads OCR_MODEL / OCR_BASE_URL
python -m evals.capture

# 2. Baseline on the current classifier model — needs the classifier backend (Vertex)
PIPELINE_MODEL=gemini-3-flash-preview python -m evals.run --baseline

# 3. Later: self-hosted classifier, compared against the baseline
PIPELINE_MODEL=<qwen-model> python -m evals.run --compare results/baseline.json
```

## Output

- `results/<timestamp>_<model>.json` — full run (model id, per-document rows, confusion).
- `results/baseline.json` — the reference run (committed).
- Console: a markdown summary (accuracy, gate false-negatives, failing rows).

Only `baseline.json` is committed; ad-hoc timestamped runs are gitignored.

## Current baseline

`gemini-3-flash-preview`: **95.8% (23/24)**, mean latency ~5.9 s/call. The single miss is the
intentionally-blurry pharmacy bill (TC002/F004), which the gate correctly routes to
`PENDING_REUPLOAD`.

## Self-hosted model comparison (classification stage)

Measured via this harness (24 docs, fixed OCR fixtures), accuracy + latency vs the Gemini baseline:

| Model | Backend | Accuracy | Mean latency | Notes |
|---|---|---|---|---|
| `gemini-3-flash-preview` | gemini | **95.8%** (23/24) | 5874 ms | baseline (external API) |
| `qwen2.5vl-ocr` (VLM reuse) | ollama | 87.5% (21/24) | 6658 ms | reuses the OCR model; **2 regressions** (HOSPITAL_BILL→DENTAL/LAB), no speed win |
| `qwen2.5:7b-instruct` (dedicated text) | ollama | 91.7% (22/24) | 5675 ms | **1 regression** (HOSPITAL_BILL→LAB_REPORT); comparable latency; fully local |

**Conclusion:** reusing the VLM for the text stages is the wrong call — a dedicated text model
(`qwen2.5:7b-instruct`) is clearly better on both accuracy and latency. It reaches 91.7% fully
self-hosted (no PHI to external APIs), ~4pp below Gemini, with one hospital-bill misclassification
likely closable via prompt tuning or a 14B model.

**Recommendation:** adopt `qwen2.5:7b-instruct` as the self-hosted stage model. Keep `gemini` as the
default backend until the accuracy gap is closed; enable self-hosting via env:

```bash
OLLAMA_MAX_LOADED_MODELS=1 \
PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:7b-instruct \
  uvicorn main:app --port 8000
```

RAM note (16 GB): the OCR VLM (~6.9 GB) and the text model (~4.7 GB) can't co-reside; with
`OLLAMA_MAX_LOADED_MODELS=1` Ollama swaps between the OCR pre-stage and the text stages, adding a
few seconds of reload per claim. The measured latencies above are pure inference (no swap during a
single-model eval).

## Deferred

Extraction field-scoring & consistency (need authored labels), end-to-end decision/amount
scoring, and an LLM-judge for the natural-language `system_must` / `rejection_reasons`.
