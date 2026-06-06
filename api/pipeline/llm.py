"""Single model call-site for the deterministic pipeline (google-genai controlled generation).

Every understanding stage calls the model through here. Swapping the backend (e.g. to a
self-hosted Qwen via an OpenAI-compatible endpoint) is a change to this one file.
"""

from __future__ import annotations

import json
import os
from typing import Any, TypeVar

from google import genai
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.getenv("PIPELINE_MODEL", "gemini-3-flash-preview")

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
) -> T:
    """Call the model with a typed payload and parse the JSON response into `output_model`.

    Uses controlled generation (`response_schema`) so the response is valid JSON matching
    the schema. Falls back to parsing `response.text` if `.parsed` is unavailable.
    """
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
