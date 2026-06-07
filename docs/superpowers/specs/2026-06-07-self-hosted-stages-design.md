# Self-Hosted Understanding Stages — Design

**Date:** 2026-06-07
**Status:** Approved design, pending implementation plan
**Milestone:** #3 of the production-grade migration. Completes the "no PHI to external LLM APIs"
north star by routing the four understanding stages off Gemini to a self-hosted model.

---

## Motivation

The deterministic pipeline calls the LLM only for four scoped understanding stages (classify /
requirements / extract / consistency), all through a single call-site (`pipeline/llm.py`). Today
that call-site uses Gemini (Vertex). Routing it to a self-hosted model removes the last PHI text
from external APIs — the original privacy goal — and OCR images already stay local (Qwen-VL).

The eval harness (milestone #2) provides the safety gate: a self-hosted model is acceptable only if
classification accuracy stays within tolerance of the committed Gemini baseline (95.8 %, 23/24).

## Decoupling principle

The code change is **independent of the model choice**: add a self-hosted backend to `llm.py` once,
then the model is a config flip and the eval harness picks the winner empirically.

---

## Goals

- Add an **Ollama (OpenAI-compatible) backend** to `pipeline/llm.py` with reliable JSON output,
  selected by config — `gemini` (current default) or `ollama`.
- Keep `structured_llm_call`'s signature and all of `stages.py` unchanged.
- Make the model an env flip (`PIPELINE_BACKEND`, `PIPELINE_BASE_URL`, `PIPELINE_MODEL`).
- Use the eval harness to choose between **Run A** (reuse the VLM) and **Run B** (dedicated 7B text
  model) based on measured accuracy **and latency** vs the baseline.

## Latency in the eval (added requirement)

The eval harness measures **per-call latency** for the classification stage (mean / median / p95,
plus per-row `latency_ms`), surfaced in the report and the `--compare` output. Latency is a
first-class part of the model decision: self-hosted inference speed and the OCR↔text reload cost on
16 GB are real tradeoffs against the Gemini baseline. The Gemini `baseline.json` is regenerated to
include latency so A/B comparisons are apples-to-apples.

## Non-Goals (this milestone)

- vLLM / GPU serving (production path; same OpenAI-compatible client, later milestone).
- Converting the deterministic `requirements` stage to pure Python (noted as future).
- Self-hosting evals for extraction/consistency (still unlabeled; classification is the gate).

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Serving (local) | **Ollama** | Only practical local option on 16 GB Apple Silicon; vLLM needs CUDA. Reuses the OCR setup. |
| Backend selection | **Config: `PIPELINE_BACKEND=gemini\|ollama`** | One code path built once; model becomes an env flip. |
| Structured output (Ollama) | **`response_format: json_object` + Pydantic validate + 1 retry** | Portable and robust across the flat *and* deeply-nested stage schemas; avoids JSON-schema→grammar explosion on the nested extraction model. Schema is communicated via the prompt. |
| Model choice | **Decided empirically by the eval harness** | Run A (reuse `qwen2.5-vl`, zero extra RAM) vs Run B (`qwen2.5:7b-instruct`, better text JSON). Pick by accuracy vs the 95.8 % baseline. |
| Acceptance gate | **Classification accuracy within tolerance of baseline** | The harness `--compare` is the definition of done. |

---

## Architecture

Only `pipeline/llm.py` changes; `stages.py`, `orchestrator.py`, `main.py` are untouched.

### Config (env)
```
PIPELINE_BACKEND   gemini | ollama          (default: gemini)
PIPELINE_MODEL     model id                 (default: gemini-3-flash-preview)
PIPELINE_BASE_URL  http://localhost:11434   (ollama backend only)
```

### `pipeline/llm.py` — two backends behind one function
```python
def structured_llm_call(system_prompt, payload, output_model, *, model=None, client=None) -> T:
    backend = os.getenv("PIPELINE_BACKEND", "gemini")
    if backend == "ollama":
        return _ollama_call(system_prompt, payload, output_model, model=model, client=client)
    return _gemini_call(system_prompt, payload, output_model, model=model, client=client)
```

- `_gemini_call`: the current implementation (google-genai `response_schema`), extracted unchanged.
- `_ollama_call`: POST `{base_url}/v1/chat/completions` with
  - `messages = [{role: system, content: system_prompt + "\n\nReturn JSON matching this schema:\n" + <compact json schema>}, {role: user, content: <payload json>}]`
  - `response_format = {"type": "json_object"}`, `temperature = 0.1`, `stream = false`
  - parse `choices[0].message.content` → `output_model.model_validate_json(...)`
  - on JSON-decode or Pydantic `ValidationError`: **one retry**; if it still fails, raise (the stage
    functions already convert this to their safe stop outcome).
- The schema hint = `json.dumps(output_model.model_json_schema())` (compact), so the model sees the
  exact target shape even though decoding isn't grammar-constrained.

### Why json_object + validate (not strict json_schema grammar)
The extraction output model is deeply nested (per-document-type field models). Converting that to a
constrained grammar (llama.cpp) is fragile/slow. `json_object` guarantees syntactic JSON; Pydantic
validation guarantees schema conformance; the retry covers transient malformed output. This is the
portable, reliable choice and also works against vLLM later. (Strict `json_schema` can be a future
tightening for the flat stages.)

---

## Model evaluation plan (the empirical decision)

After the backend is built, capture-free (fixtures already exist):

```
# Baseline already committed: gemini-3-flash-preview = 95.8% (23/24)

# Run A — reuse the VLM (one model, zero extra RAM)
PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5vl-ocr \
  python -m evals.run --compare results/baseline.json

# Run B — dedicated text model (better text JSON; OCR<->text reload on 16GB)
ollama pull qwen2.5:7b-instruct
PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:7b-instruct \
  python -m evals.run --compare results/baseline.json
```

**Decision rule:** if Run A is within tolerance of baseline (target: ≥ ~90 %, no critical-doc
regressions) → choose A (RAM-optimal, one model). Else choose B. Record the chosen config in the
eval README and a new `results/` run; do **not** overwrite the Gemini `baseline.json`.

### RAM note
Set `OLLAMA_MAX_LOADED_MODELS=1` so the OCR and text models swap cleanly rather than co-residing on
16 GB. Run A avoids swaps entirely (single model for OCR + stages).

---

## Testing

- Unit-test `_ollama_call` with a **mocked HTTP client** (respx/fake): asserts it posts
  `response_format=json_object`, includes the schema hint, parses a valid JSON response into the
  model, and **retries once** then raises on persistent invalid JSON.
- Unit-test backend dispatch: `PIPELINE_BACKEND=ollama` routes to `_ollama_call`; default routes to
  `_gemini_call` (both via injected fakes — no network).
- Existing `test_llm.py` (gemini path) stays green.
- The model-quality decision is made by the **eval harness** (live), not unit tests.

---

## Acceptance criteria

1. `structured_llm_call` works on both backends; full unit suite green.
2. `PIPELINE_BACKEND=ollama` runs the whole pipeline with **no Gemini calls** (privacy goal met when
   enabled).
3. An eval run with the chosen self-hosted model is committed under `results/`, with the chosen
   config and its accuracy-vs-baseline documented in `evals/README.md`.

---

## Future Work

- vLLM + guided-JSON for production (GPU); strict `json_schema` for flat stages.
- Convert `requirements` to deterministic Python (removes one LLM call).
- Extraction/consistency eval dimensions once labels exist, to validate those stages on the
  self-hosted model too.
