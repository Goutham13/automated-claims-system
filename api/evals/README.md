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

`gemini-3-flash-preview`: **95.8% (23/24)**. The single miss is the intentionally-blurry
pharmacy bill (TC002/F004), which the gate correctly routes to `PENDING_REUPLOAD`.

## Deferred

Extraction field-scoring & consistency (need authored labels), end-to-end decision/amount
scoring, and an LLM-judge for the natural-language `system_must` / `rejection_reasons`.
