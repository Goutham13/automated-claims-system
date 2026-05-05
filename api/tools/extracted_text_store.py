from __future__ import annotations

import re
from typing import Any

from google.adk.tools import ToolContext
from google.genai.types import Part


def _safe_filename_component(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value)
    return value[:120] or "file"


async def save_extracted_document_text(
    file_id: str,
    file_name: str,
    document_text: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """
    Persist extracted document text for reuse.

    Saves the full text as a session-scoped artifact and records a small index in
    `session.state` under the `doc:` namespace so downstream steps (and later
    invocations) can reference it without re-OCRing.

    Args:
        file_id: Stable file identifier (e.g. "F001").
        file_name: Original uploaded filename.
        document_text: Extracted plain text (best-effort OCR).
        tool_context: ADK-injected ToolContext (provides state + artifacts APIs).
    """
    safe_name = _safe_filename_component(file_name)
    # NOTE: ADK Web's artifact routes treat `{artifact_name}` as a single path
    # segment (not `{artifact_name:path}`), so artifact filenames must not
    # contain `/` or they won't be retrievable from the UI.
    filename = f"extracted_text__{file_id}-{safe_name}.txt"

    artifact = Part.from_bytes(
        data=(document_text or "").encode("utf-8"),
        mime_type="text/plain; charset=utf-8",
    )

    version = await tool_context.save_artifact(filename=filename, artifact=artifact)

    index_key = "doc:extracted_text_index"
    index = tool_context.state.get(index_key)
    if not isinstance(index, dict):
        index = {}

    index[file_id] = {
        "file_id": file_id,
        "file_name": file_name,
        "artifact_filename": filename,
        "artifact_version": version,
        "char_count": len(document_text or ""),
    }
    tool_context.state[index_key] = index

    return {"status": "saved", **index[file_id]}
