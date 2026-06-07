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

## All-stage comparison (instruct vs gemini)

`python -m evals.stage_compare` compares the self-hosted candidate against the Gemini reference across
all four stages — accuracy vs labels for classification/requirements, agreement-vs-Gemini for
extraction/consistency (no gold labels), plus per-stage latency. Stage-isolated (ground-truth
`actual_types` feed requirements/extraction; consistency uses the reference model's snapshots).

Result — `qwen2.5:7b-instruct` (ollama) vs `gemini-3-flash-preview`:

| stage | metric | gemini (ref) | instruct (cand) |
|---|---|---|---|
| classification | accuracy vs truth | 95.8% | 91.7% |
| requirements | accuracy vs computed rule | 100% | 91.7% |
| extraction | field-agreement vs ref | — | **58.3%** |
| consistency | outcome-agreement vs ref | — | 100% |

Mean latency (ms, ref → cand): classification 20618→5699 · requirements 2972→1587 ·
extraction 6504→20450 · consistency 5148→2561. Extraction critical-field completeness: ref 91.7%,
cand 100%.

**Read:** the local instruct model is viable for **classification, requirements, and consistency**
(close accuracy / full outcome-agreement, and faster on those stages). **Extraction is the risk** —
only 58% field-agreement with Gemini despite higher completeness, meaning the local model fills all
critical fields but with materially different *values* (likely date/amount/name normalization, to be
investigated). Extraction needs prompt tuning / a larger model / authored gold labels before it can
be trusted self-hosted; classification/requirements/consistency can move to the local model now.
Extraction latency is also ~3× slower locally (large nested JSON output).

(`gemini` remains the default backend; the self-hosted candidate is opt-in via `PIPELINE_BACKEND=ollama`.)

## 4-candidate comparison vs the gemini-2.5-pro golden set (fair extraction)

Reference = cached `gemini-2.5-pro` golden set (`evals/reference/`, captured once via
`capture_reference`). Classification/requirements scored vs **truth**; extraction/consistency are
**agreement vs the golden set**. Extraction uses **type-aware** matching (`field_compare`): dates,
numbers, case, and list order/normalization no longer count as mismatches.

| Candidate | Classif (truth) | Requirements | Extraction all-field (exact) | Extraction critical | Consistency | Ext. latency |
|---|---|---|---|---|---|---|
| gemini-3-flash | 95.8% | 100% | 97.5% (90.3%) | 100% | 91.7% | 6.9 s |
| qwen2.5:7b-instruct | 91.7% | 91.7% | 62.8% (56.4%) | 79.2% | 100% | 22.5 s |
| qwen2.5:14b | 87.5% | 100% | 70.6% (67.5%) | 87.5% | 100% | 54 s |
| llama3.1:8b | 95.8% | 8.3% | 41.4% (38.3%) | 51.4% | 8.3% | 35 s |
| _ref: gemini-2.5-pro_ | 91.7% | 100% | — | — | — | — |

**Findings:**
- **gemini-3-flash ≈ pro** on all stages (extraction 97.5% / critical 100%) — the strong, cheap
  option, but external API.
- **Self-hosted extraction gap is real but narrower than naive exact-match implied** (~58%).
  `qwen2.5:14b` reaches **87.5% critical-field** agreement (7b: 79.2%) — a bigger model helps the
  hard stage — but classification dips to 87.5% and extraction is **~54 s/doc** on 16 GB.
- **`llama3.1:8b` is unsuitable** for the structured stages: requirements & consistency ≈8.3%
  (fails to emit valid JSON reliably), despite strong classification.
- Pro itself is only 91.7% on classification (flash/llama beat it vs truth).

**Recommendation:** among self-hosted, `qwen2.5:14b` is most accurate on the hard stages but
latency-heavy; `qwen2.5:7b` is the balanced choice; `llama3.1:8b` is out. Extraction is the residual
gap vs Gemini. Default backend stays `gemini`.

## Deferred

Extraction field-scoring & consistency (need authored labels), end-to-end decision/amount
scoring, and an LLM-judge for the natural-language `system_must` / `rejection_reasons`.
