"""Single model call-site for the deterministic pipeline.

Every understanding stage calls the model through `structured_llm_call`, which dispatches to a
backend by `PIPELINE_BACKEND`:
  - "gemini" (default): google-genai controlled generation (Vertex).
  - "ollama": self-hosted, OpenAI-compatible endpoint with JSON output + Pydantic validation.

Swapping the stage model is a config change (env), not a code change.
"""

from __future__ import annotations

import json
import os
from typing import Any, TypeVar

import httpx
from google import genai
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.getenv("PIPELINE_MODEL", "gemini-3-flash-preview")
DEFAULT_OLLAMA_MODEL = "qwen2.5vl-ocr"

_client: genai.Client | None = None


def _default_client() -> genai.Client:
    """Lazily build a shared genai client (reads Vertex/project/location from env)."""
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def structured_llm_call(
    system_prompt: str,
    payload: BaseModel | dict[str, Any],
    output_model: type[T],
    *,
    model: str | None = None,
    client: Any | None = None,
    backend: str | None = None,
) -> T:
    """Call the configured backend with a typed payload; return a parsed `output_model`.

    `backend` overrides `PIPELINE_BACKEND` for this call (used by the eval harness to drive
    both gemini and a self-hosted candidate within one process).
    """
    backend = (backend or os.getenv("PIPELINE_BACKEND", "gemini")).lower()
    if backend == "ollama":
        return _ollama_call(system_prompt, payload, output_model, model=model)
    return _gemini_call(system_prompt, payload, output_model, model=model, client=client)


def _gemini_call(
    system_prompt: str,
    payload: BaseModel | dict[str, Any],
    output_model: type[T],
    *,
    model: str | None = None,
    client: Any | None = None,
) -> T:
    """Gemini (Vertex) backend via google-genai controlled generation (`response_schema`)."""
    payload_str = payload.model_dump_json() if isinstance(payload, BaseModel) else json.dumps(payload)
    cli = client or _default_client()
    resp = cli.models.generate_content(
        model=model or DEFAULT_MODEL,
        contents=payload_str,
        config=GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json",
            response_schema=output_model,
            temperature=0.1,
        ),
    )
    parsed = getattr(resp, "parsed", None)
    if isinstance(parsed, output_model):
        return parsed
    return output_model.model_validate_json(resp.text)


def _ollama_call(
    system_prompt: str,
    payload: BaseModel | dict[str, Any],
    output_model: type[T],
    *,
    model: str | None = None,
    base_url: str | None = None,
    retries: int = 1,
) -> T:
    """Self-hosted backend: OpenAI-compatible JSON output, validated by Pydantic with one retry.

    Uses `response_format: json_object` (portable, robust for nested schemas) and communicates the
    exact target shape via the system prompt. Schema conformance is enforced by validation; a
    transient malformed response is retried once before raising.
    """
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
