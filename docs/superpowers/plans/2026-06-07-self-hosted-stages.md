# Self-Hosted Understanding Stages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add an Ollama (OpenAI-compatible) backend to `pipeline/llm.py` behind a config switch, then use the eval harness to choose the self-hosted model (VLM reuse vs dedicated 7B) against the Gemini baseline.

**Architecture:** `structured_llm_call` dispatches on `PIPELINE_BACKEND` to `_gemini_call` (existing) or `_ollama_call` (new: `/v1/chat/completions`, `response_format=json_object`, Pydantic-validate + 1 retry). Only `pipeline/llm.py` changes. Model = env (`PIPELINE_MODEL`/`PIPELINE_BASE_URL`). Decision made by `evals.run --compare`.

**Tech Stack:** Python 3.11+, httpx, Pydantic v2, pytest + respx. Ollama (qwen2.5vl-ocr; qwen2.5:7b-instruct).

**Reference spec:** `docs/superpowers/specs/2026-06-07-self-hosted-stages-design.md`

---

### Task 1: Refactor `llm.py` to backend dispatch (gemini extracted) + test

**Files:** Modify `api/pipeline/llm.py`; Create `api/tests/test_llm_dispatch.py`

- [ ] **Step 1: Failing test** — `api/tests/test_llm_dispatch.py`
```python
import pipeline.llm as llm
from pydantic import BaseModel


class Out(BaseModel):
    label: str


def test_dispatch_to_ollama(monkeypatch):
    monkeypatch.setenv("PIPELINE_BACKEND", "ollama")
    called = {}
    monkeypatch.setattr(llm, "_ollama_call", lambda *a, **k: called.setdefault("ollama", True) or Out(label="o"))
    monkeypatch.setattr(llm, "_gemini_call", lambda *a, **k: called.setdefault("gemini", True) or Out(label="g"))
    out = llm.structured_llm_call("sys", {"x": 1}, Out)
    assert out.label == "o" and called == {"ollama": True}


def test_dispatch_to_gemini_by_default(monkeypatch):
    monkeypatch.delenv("PIPELINE_BACKEND", raising=False)
    monkeypatch.setattr(llm, "_gemini_call", lambda *a, **k: Out(label="g"))
    monkeypatch.setattr(llm, "_ollama_call", lambda *a, **k: Out(label="o"))
    assert llm.structured_llm_call("sys", {"x": 1}, Out).label == "g"
```

- [ ] **Step 2: Run → fails** (`cd api && uv run pytest tests/test_llm_dispatch.py -q`) — `_ollama_call` missing.

- [ ] **Step 3: Refactor `llm.py`** — rename the current body to `_gemini_call(...)`, add dispatch + a stub `_ollama_call` (real impl in Task 2). Keep `structured_llm_call`'s signature.
```python
def structured_llm_call(system_prompt, payload, output_model, *, model=None, client=None):
    backend = os.getenv("PIPELINE_BACKEND", "gemini").lower()
    if backend == "ollama":
        return _ollama_call(system_prompt, payload, output_model, model=model)
    return _gemini_call(system_prompt, payload, output_model, model=model, client=client)


def _gemini_call(system_prompt, payload, output_model, *, model=None, client=None):
    # ... existing google-genai body unchanged ...


def _ollama_call(system_prompt, payload, output_model, *, model=None, base_url=None, retries=1):
    raise NotImplementedError  # Task 2
```

- [ ] **Step 4: Run → dispatch test passes; `test_llm.py` (gemini) still passes.**
- [ ] **Step 5: Commit** — `refactor(pipeline): dispatch structured_llm_call by PIPELINE_BACKEND`

---

### Task 2: Implement `_ollama_call` (json_object + validate + retry) + test

**Files:** Modify `api/pipeline/llm.py`; Create `api/tests/test_llm_ollama.py`

- [ ] **Step 1: Failing test** — `api/tests/test_llm_ollama.py`
```python
import httpx
import pytest
import respx
from pydantic import BaseModel

import pipeline.llm as llm


class Out(BaseModel):
    label: str
    score: float


def _resp(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@respx.mock
def test_ollama_parses_and_sends_json_object(monkeypatch):
    monkeypatch.setenv("PIPELINE_BASE_URL", "http://test-llm")
    monkeypatch.setenv("PIPELINE_MODEL", "qwen2.5vl-ocr")
    route = respx.post("http://test-llm/v1/chat/completions").mock(
        return_value=_resp('{"label":"PRESCRIPTION","score":0.9}'))
    out = llm._ollama_call("classify", {"document_text": "x"}, Out)
    assert out.label == "PRESCRIPTION" and out.score == 0.9
    body = route.calls.last.request.content.decode()
    assert "json_object" in body
    assert "qwen2.5vl-ocr" in body
    assert "schema" in body.lower()  # schema hint included


@respx.mock
def test_ollama_retries_once_then_raises(monkeypatch):
    monkeypatch.setenv("PIPELINE_BASE_URL", "http://test-llm")
    monkeypatch.setenv("PIPELINE_MODEL", "m")
    route = respx.post("http://test-llm/v1/chat/completions").mock(
        return_value=_resp("not json"))
    with pytest.raises(Exception):
        llm._ollama_call("sys", {"x": 1}, Out)
    assert route.call_count == 2  # initial + 1 retry


@respx.mock
def test_ollama_retry_recovers(monkeypatch):
    monkeypatch.setenv("PIPELINE_BASE_URL", "http://test-llm")
    monkeypatch.setenv("PIPELINE_MODEL", "m")
    respx.post("http://test-llm/v1/chat/completions").mock(side_effect=[
        _resp("garbage"), _resp('{"label":"L","score":0.1}')])
    out = llm._ollama_call("sys", {"x": 1}, Out)
    assert out.label == "L"
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement `_ollama_call`** in `llm.py`:
```python
import httpx
from pydantic import ValidationError

DEFAULT_OLLAMA_MODEL = "qwen2.5vl-ocr"


def _ollama_call(system_prompt, payload, output_model, *, model=None, base_url=None, retries=1):
    base = (base_url or os.getenv("PIPELINE_BASE_URL", "http://localhost:11434")).rstrip("/")
    mdl = model or os.getenv("PIPELINE_MODEL", DEFAULT_OLLAMA_MODEL)
    payload_str = payload.model_dump_json() if isinstance(payload, BaseModel) else json.dumps(payload)
    schema = json.dumps(output_model.model_json_schema())
    sys_msg = f"{system_prompt}\n\nReturn ONLY a JSON object matching this schema:\n{schema}"
    body = {
        "model": mdl,
        "stream": False,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": payload_str},
        ],
        "response_format": {"type": "json_object"},
    }
    url = f"{base}/v1/chat/completions"
    last_err: Exception | None = None
    for _ in range(retries + 1):
        resp = httpx.post(url, json=body, timeout=120)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        try:
            return output_model.model_validate_json(content)
        except (ValidationError, ValueError) as exc:
            last_err = exc
    raise last_err if last_err else RuntimeError("ollama call failed")
```

- [ ] **Step 4: Run → passes; full suite green** (`cd api && uv run pytest -q`).
- [ ] **Step 5: Commit** — `feat(pipeline): add Ollama backend with JSON validation and retry`

---

### Task 3: Empirical model selection via eval harness + document (manual)

**Files:** Modify `api/evals/README.md`; add chosen `api/evals/results/<run>.json`

> Needs Ollama running. Fixtures already captured; `baseline.json` (Gemini 95.8%) committed. Do NOT overwrite `baseline.json`.

- [ ] **Step 1: Run A — reuse the VLM**
```bash
cd api && set -a; source .env; set +a
PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5vl-ocr OLLAMA_MAX_LOADED_MODELS=1 \
  uv run python -m evals.run --compare results/baseline.json
```
Record accuracy + regressions.

- [ ] **Step 2: Run B — dedicated text model**
```bash
ollama pull qwen2.5:7b-instruct
cd api && set -a; source .env; set +a
PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:7b-instruct OLLAMA_MAX_LOADED_MODELS=1 \
  uv run python -m evals.run --compare results/baseline.json
```
Record accuracy + regressions.

- [ ] **Step 3: Decide** — pick the model: if Run A ≥ ~90% and no critical-doc regression → A (RAM-optimal); else B. Keep the chosen run's `results/<timestamp>_<model>.json` (gitignore keeps only baseline.json + this if force-added).

- [ ] **Step 4: Document** — update `api/evals/README.md` with a "Self-hosted results" section: A vs B accuracy, the chosen model, and the exact env to run the pipeline fully self-hosted:
```
PIPELINE_BACKEND=ollama PIPELINE_MODEL=<chosen> OLLAMA_MAX_LOADED_MODELS=1
```
Force-add the chosen result file: `git add -f api/evals/results/<chosen>.json`.

- [ ] **Step 5: Commit** — `feat(evals): self-hosted stage model selection (A vs B) + chosen baseline`

---

## Self-Review

**Spec coverage:** Ollama backend + dispatch (T1/T2), json_object+validate+retry (T2), config-driven model (T1/T2), empirical A-vs-B via harness (T3), unchanged stages/orchestrator (only llm.py touched), acceptance documented (T3). ✓
**Placeholder scan:** all code shown; T3 is explicitly manual/live. ✓
**Type consistency:** `structured_llm_call(system_prompt, payload, output_model, *, model, client)` unchanged; `_gemini_call`/`_ollama_call` share the same return contract (an `output_model` instance). ✓

## Execution Handoff
Inline execution via executing-plans. Tasks 1–2 are TDD/committable offline; Task 3 needs Ollama and is run live at the end.
