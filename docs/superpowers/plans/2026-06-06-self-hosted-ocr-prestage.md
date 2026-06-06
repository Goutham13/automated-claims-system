# Self-Hosted VLM OCR Pre-Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move OCR out of the root Gemini agent into a deterministic pre-stage backed by a self-hosted Qwen2.5-VL model (run locally via Ollama), so no document images ever reach a Gemini agent.

**Architecture:** A new `api/ocr/` package rasterizes documents (PDF→PNG), calls Qwen via Ollama's OpenAI-compatible API, and returns extracted text. `main.py`'s `claim_events` runs this pre-stage before invoking the agent, injects text-only input, emits a synthetic `TEXT_EXTRACTION` SSE step, and drops all image parts. The root agent prompt loses its self-OCR stage.

**Tech Stack:** Python 3.11, FastAPI, Google ADK, PyMuPDF (rasterize), httpx (HTTP), Ollama + `qwen2.5vl:7b`, pytest + respx (tests).

**Reference spec:** `docs/superpowers/specs/2026-06-06-self-hosted-ocr-prestage-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `api/ocr/__init__.py` | Package exports (`OcrClient`, `OcrResult`, `extract_text_for_documents`). |
| `api/ocr/rasterize.py` | Document bytes + mime → list of PNG bytes (one per page). |
| `api/ocr/client.py` | `OcrClient`: one image → text via Ollama; retry; `OcrUnavailableError`. |
| `api/ocr/service.py` | `extract_text_for_documents`: orchestrates rasterize→OCR per doc; failure isolation; service-unavailable signal. |
| `api/main.py` (modify) | Run pre-stage, emit synthetic step, build text-only Content, short-circuit on outage. |
| `api/agents/agent.py` (modify) | Remove `TEXT_EXTRACTION` stage + `save_extracted_document_text` tool. |
| `api/pyproject.toml` (modify) | Add `pymupdf`, `httpx` deps; dev deps; register `ocr` package. |
| `api/tests/...` | Unit + integration tests. |

---

### Task 1: Project + test scaffolding

**Files:**
- Modify: `api/pyproject.toml`
- Modify: `api/requirements.txt`
- Create: `api/tests/__init__.py`
- Create: `api/pytest.ini`

- [ ] **Step 1: Add runtime + dev dependencies**

Edit `api/pyproject.toml` — add to `dependencies`:
```toml
  "pymupdf>=1.24",
  "httpx>=0.27",
```
Add a dev group and register the new package after `[tool.hatch.build.targets.wheel]`:
```toml
[tool.hatch.build.targets.wheel]
packages = ["agents", "ocr"]

[dependency-groups]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "respx>=0.21",
]
```

- [ ] **Step 2: Mirror runtime deps into requirements.txt**

Append to `api/requirements.txt`:
```
pymupdf>=1.24
httpx>=0.27
```

- [ ] **Step 3: Add pytest config**

Create `api/pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 4: Create tests package**

Create `api/tests/__init__.py` (empty file).

- [ ] **Step 5: Install and verify**

Run: `cd api && uv sync && uv run pytest -q`
Expected: pytest runs, "no tests ran" (exit 5) or 0 collected — confirms tooling works.

- [ ] **Step 6: Commit**

```bash
git add api/pyproject.toml api/requirements.txt api/pytest.ini api/tests/__init__.py
git commit -m "chore(ocr): add pymupdf/httpx deps and pytest scaffolding"
```

---

### Task 2: Rasterize documents to PNG (`api/ocr/rasterize.py`)

**Files:**
- Create: `api/ocr/__init__.py`
- Create: `api/ocr/rasterize.py`
- Create: `api/tests/test_rasterize.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_rasterize.py`:
```python
import fitz  # PyMuPDF
import pytest

from ocr.rasterize import to_images, MAX_PDF_PAGES


def _make_pdf(num_pages: int) -> bytes:
    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), "Hello claim")
    data = doc.tobytes()
    doc.close()
    return data


def _png_magic(b: bytes) -> bool:
    return b[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_passthrough_unchanged():
    raw = b"\x89PNG\r\n\x1a\n-fake-image-bytes"
    assert to_images(raw, "image/png") == [raw]
    assert to_images(raw, "image/jpeg") == [raw]


def test_pdf_one_image_per_page():
    pdf = _make_pdf(3)
    images = to_images(pdf, "application/pdf")
    assert len(images) == 3
    assert all(_png_magic(img) for img in images)


def test_pdf_page_cap():
    pdf = _make_pdf(MAX_PDF_PAGES + 5)
    images = to_images(pdf, "application/pdf")
    assert len(images) == MAX_PDF_PAGES


def test_corrupt_pdf_raises():
    with pytest.raises(Exception):
        to_images(b"not a real pdf", "application/pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_rasterize.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ocr'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/ocr/__init__.py`:
```python
"""Self-hosted VLM OCR pre-stage package."""
```

Create `api/ocr/rasterize.py`:
```python
"""Convert uploaded document bytes into PNG page images for the OCR VLM."""

from __future__ import annotations

import os

import fitz  # PyMuPDF

MAX_PDF_PAGES = int(os.getenv("OCR_MAX_PDF_PAGES", "10"))
_RENDER_DPI = int(os.getenv("OCR_RENDER_DPI", "200"))


def to_images(data: bytes, mime_type: str) -> list[bytes]:
    """Return a list of PNG byte strings, one per page.

    - image/* inputs are passed through unchanged (already a single image).
    - application/pdf is rendered page-by-page to PNG at _RENDER_DPI,
      capped at MAX_PDF_PAGES.
    Raises on an unopenable PDF (caller treats as a per-document failure).
    """
    mime = (mime_type or "").lower()
    if mime.startswith("image/"):
        return [data]

    if mime == "application/pdf":
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            pages: list[bytes] = []
            for index, page in enumerate(doc):
                if index >= MAX_PDF_PAGES:
                    break
                pixmap = page.get_pixmap(dpi=_RENDER_DPI)
                pages.append(pixmap.tobytes("png"))
            return pages
        finally:
            doc.close()

    raise ValueError(f"Unsupported mime_type for rasterization: {mime_type!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_rasterize.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add api/ocr/__init__.py api/ocr/rasterize.py api/tests/test_rasterize.py
git commit -m "feat(ocr): rasterize PDF/image bytes to PNG pages"
```

---

### Task 3: OCR client (`api/ocr/client.py`)

**Files:**
- Create: `api/ocr/client.py`
- Create: `api/tests/test_client.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_client.py`:
```python
import httpx
import pytest
import respx

from ocr.client import OcrClient, OcrUnavailableError

PNG = b"\x89PNG\r\n\x1a\n-img"


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@respx.mock
def test_ocr_image_returns_text_and_sends_data_url():
    route = respx.post("http://test-ocr/v1/chat/completions").mock(
        return_value=_ok_response("PHARMACY BILL\nTotal 420")
    )
    client = OcrClient(base_url="http://test-ocr", model="qwen2.5vl:7b")
    text = client.ocr_image(PNG)

    assert text == "PHARMACY BILL\nTotal 420"
    sent = route.calls.last.request
    body = sent.content.decode()
    assert "qwen2.5vl:7b" in body
    assert "data:image/png;base64," in body


@respx.mock
def test_retry_then_success_on_5xx():
    route = respx.post("http://test-ocr/v1/chat/completions").mock(
        side_effect=[httpx.Response(503), _ok_response("ok")]
    )
    client = OcrClient(base_url="http://test-ocr", retry_backoff=0)
    assert client.ocr_image(PNG) == "ok"
    assert route.call_count == 2


@respx.mock
def test_connection_error_raises_unavailable():
    respx.post("http://test-ocr/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("refused")
    )
    client = OcrClient(base_url="http://test-ocr", retry_backoff=0)
    with pytest.raises(OcrUnavailableError):
        client.ocr_image(PNG)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ocr.client'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/ocr/client.py`:
```python
"""HTTP client for a self-hosted Qwen-VL OCR endpoint (Ollama OpenAI-compatible)."""

from __future__ import annotations

import base64
import os
import time

import httpx

OCR_SYSTEM_PROMPT = """You are an OCR transcription engine for medical claim documents.

Rules (follow exactly):
- Transcribe ONLY text that is visibly present in the image.
- Do NOT guess missing, blurry, or partially obscured tokens.
- Do NOT use outside knowledge or context from other documents.
- For any illegible region, write [UNREADABLE] instead of inventing content.
- If the image is mostly blank, return little or no text — do not pad.
- Output PLAIN TEXT only. No commentary, no markdown, no explanations.
"""


class OcrUnavailableError(RuntimeError):
    """Raised when the OCR service cannot be reached (connection-level failure)."""


class OcrClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
        retry_backoff: float = 2.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("OCR_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OCR_MODEL", "qwen2.5vl:7b")
        self.timeout = timeout
        self.retry_backoff = retry_backoff

    def ocr_image(self, png_bytes: bytes) -> str:
        """Transcribe a single PNG image to text. One retry on transient failure."""
        b64 = base64.b64encode(png_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "temperature": 0,
            "stream": False,
            "messages": [
                {"role": "system", "content": OCR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe this document image."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                },
            ],
        }
        url = f"{self.base_url}/v1/chat/completions"

        last_exc: Exception | None = None
        for attempt in range(2):  # initial try + one retry
            try:
                resp = httpx.post(url, json=payload, timeout=self.timeout)
                if resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        "server error", request=resp.request, response=resp
                    )
                    if attempt == 0:
                        time.sleep(self.retry_backoff)
                        continue
                    raise OcrUnavailableError(f"OCR server error {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                return (data["choices"][0]["message"]["content"] or "").strip()
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(self.retry_backoff)
                    continue
                raise OcrUnavailableError(str(exc)) from exc

        raise OcrUnavailableError(str(last_exc))  # defensive; not normally reached
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd api && uv run pytest tests/test_client.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add api/ocr/client.py api/tests/test_client.py
git commit -m "feat(ocr): add Ollama OCR client with retry and unavailable signal"
```

---

### Task 4: OCR service orchestration (`api/ocr/service.py`)

**Files:**
- Create: `api/ocr/service.py`
- Modify: `api/ocr/__init__.py`
- Create: `api/tests/test_service.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_service.py`:
```python
from ocr.client import OcrUnavailableError
from ocr.service import extract_text_for_documents


def _doc(file_id: str, mime: str = "image/png", data: bytes = b"\x89PNG\r\n\x1a\nx"):
    return {"file_id": file_id, "file_name": f"{file_id}.png", "mime_type": mime, "bytes": data}


class FakeClient:
    def __init__(self, mapping=None, raise_unavailable=False):
        self.mapping = mapping or {}
        self.raise_unavailable = raise_unavailable
        self.calls = 0

    def ocr_image(self, png_bytes: bytes) -> str:
        self.calls += 1
        if self.raise_unavailable:
            raise OcrUnavailableError("down")
        return self.mapping.get(png_bytes, "DEFAULT TEXT")


def test_single_image_success():
    batch = extract_text_for_documents([_doc("F001")], client=FakeClient())
    assert batch.service_unavailable is False
    assert len(batch.results) == 1
    r = batch.results[0]
    assert r.ok and r.file_id == "F001" and r.page_count == 1
    assert r.document_text == "DEFAULT TEXT"


def test_multi_page_pdf_join(monkeypatch):
    # Force rasterize to yield two pages without a real PDF.
    monkeypatch.setattr("ocr.service.to_images", lambda data, mime: [b"p1", b"p2"])
    client = FakeClient(mapping={b"p1": "PAGE ONE", b"p2": "PAGE TWO"})
    doc = {"file_id": "F002", "file_name": "bill.pdf", "mime_type": "application/pdf", "bytes": b"%PDF"}
    batch = extract_text_for_documents([doc], client=client)
    r = batch.results[0]
    assert r.page_count == 2
    assert "PAGE ONE" in r.document_text and "PAGE TWO" in r.document_text


def test_one_doc_failure_isolated(monkeypatch):
    def boom(data, mime):
        if mime == "application/pdf":
            raise ValueError("corrupt")
        return [b"img"]
    monkeypatch.setattr("ocr.service.to_images", boom)
    docs = [_doc("F001"), {"file_id": "F002", "file_name": "x.pdf",
                           "mime_type": "application/pdf", "bytes": b"bad"}]
    batch = extract_text_for_documents(docs, client=FakeClient())
    assert batch.service_unavailable is False
    by_id = {r.file_id: r for r in batch.results}
    assert by_id["F001"].ok is True
    assert by_id["F002"].ok is False and by_id["F002"].document_text == ""


def test_all_fail_unavailable_short_circuit():
    docs = [_doc("F001"), _doc("F002")]
    batch = extract_text_for_documents(docs, client=FakeClient(raise_unavailable=True))
    assert batch.service_unavailable is True
    assert all(r.ok is False for r in batch.results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ocr.service'`.

- [ ] **Step 3: Write minimal implementation**

Create `api/ocr/service.py`:
```python
"""Orchestrate the OCR pre-stage: document bytes -> extracted text per file."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ocr.client import OcrClient, OcrUnavailableError
from ocr.rasterize import to_images

_PAGE_SEP = "\n\n--- page {n} ---\n"

_shared_client: OcrClient | None = None


def _default_client() -> OcrClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = OcrClient()
    return _shared_client


@dataclass
class OcrResult:
    file_id: str
    file_name: str
    document_text: str
    page_count: int
    ok: bool
    error: str | None = None


@dataclass
class OcrBatchResult:
    results: list[OcrResult] = field(default_factory=list)
    service_unavailable: bool = False


def extract_text_for_documents(
    documents: list[dict[str, Any]],
    client: OcrClient | None = None,
) -> OcrBatchResult:
    """OCR every document sequentially. Failures are captured, never raised.

    `service_unavailable` is True only when the OCR endpoint was unreachable
    (connection-level) AND no document produced any text.
    """
    ocr = client or _default_client()
    results: list[OcrResult] = []
    saw_unavailable = False

    for doc in documents:
        file_id = doc["file_id"]
        file_name = doc.get("file_name", file_id)
        try:
            images = to_images(doc["bytes"], doc.get("mime_type", ""))
            page_texts: list[str] = []
            for n, png in enumerate(images, start=1):
                text = ocr.ocr_image(png)
                if len(images) > 1:
                    page_texts.append(_PAGE_SEP.format(n=n) + text)
                else:
                    page_texts.append(text)
            results.append(
                OcrResult(
                    file_id=file_id,
                    file_name=file_name,
                    document_text="".join(page_texts).strip(),
                    page_count=len(images),
                    ok=True,
                )
            )
        except OcrUnavailableError as exc:
            saw_unavailable = True
            results.append(OcrResult(file_id, file_name, "", 0, False, str(exc)))
        except Exception as exc:  # rasterize failure, malformed doc, etc.
            results.append(OcrResult(file_id, file_name, "", 0, False, str(exc)))

    service_unavailable = saw_unavailable and all(not r.ok for r in results)
    return OcrBatchResult(results=results, service_unavailable=service_unavailable)
```

- [ ] **Step 4: Export the public API**

Replace `api/ocr/__init__.py` contents:
```python
"""Self-hosted VLM OCR pre-stage package."""

from ocr.client import OcrClient, OcrUnavailableError
from ocr.service import OcrBatchResult, OcrResult, extract_text_for_documents

__all__ = [
    "OcrClient",
    "OcrUnavailableError",
    "OcrBatchResult",
    "OcrResult",
    "extract_text_for_documents",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd api && uv run pytest tests/test_service.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add api/ocr/service.py api/ocr/__init__.py api/tests/test_service.py
git commit -m "feat(ocr): add OCR service orchestration with failure isolation"
```

---

### Task 5: Wire pre-stage into `claim_events` (`api/main.py`)

**Files:**
- Modify: `api/main.py` (imports; `claim_events` around lines 332-345)
- Create: `api/tests/test_prestage_wiring.py`

- [ ] **Step 1: Write the failing test**

Create `api/tests/test_prestage_wiring.py`:
```python
import json

from main import build_agent_content, ocr_step_event, OCR_UNAVAILABLE_STATUS
from ocr.service import OcrBatchResult, OcrResult


def _metadata():
    return {"claim_id": "c1", "member_id": "M1", "documents": [
        {"file_id": "F001", "file_name": "bill.png", "mime_type": "image/png"},
    ]}


def test_build_content_is_text_only():
    batch = OcrBatchResult(results=[OcrResult("F001", "bill.png", "PHARMACY BILL", 1, True)])
    content = build_agent_content(_metadata(), batch)
    # No part may carry inline binary data.
    for part in content.parts:
        assert getattr(part, "inline_data", None) is None
        assert part.text is not None
    blob = "\n".join(p.text for p in content.parts)
    assert "PHARMACY BILL" in blob
    assert "F001" in blob


def test_ocr_step_event_shape():
    batch = OcrBatchResult(results=[OcrResult("F001", "bill.png", "abc", 1, True)])
    event = ocr_step_event("c1", "u1", "s1", batch)
    step = event["actions"]["state_delta"]["TEXT_EXTRACTION"]
    assert step["status"] == "COMPLETED"
    assert "key_findings" in step


def test_unavailable_status_constant():
    assert OCR_UNAVAILABLE_STATUS == "MANUAL_REVIEW"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd api && uv run pytest tests/test_prestage_wiring.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_agent_content' from 'main'`.

- [ ] **Step 3: Add imports and helper functions to `main.py`**

Add near the other imports (after `import db` at line 27):
```python
import asyncio

from ocr.service import OcrBatchResult, extract_text_for_documents
```

Add these helpers above `create_claim` (e.g. after `_lookup_member`, ~line 225):
```python
OCR_UNAVAILABLE_STATUS = "MANUAL_REVIEW"


def build_agent_content(metadata: dict[str, Any], batch: OcrBatchResult) -> Content:
    """Build a TEXT-ONLY Content for the agent: metadata + per-file OCR text.

    Critical privacy invariant: this function must never attach image bytes.
    """
    text_by_id = {r.file_id: r.document_text for r in batch.results}
    docs = metadata.get("documents", [])
    for d in docs:
        d["document_text"] = text_by_id.get(d["file_id"], "")

    parts: list[Part] = [
        Part.from_text(text="Process this claim intake request:\n" + json.dumps(metadata))
    ]
    return Content(role="user", parts=parts)


def ocr_step_event(claim_id: str, user_id: str, session_id: str, batch: OcrBatchResult) -> dict:
    """Synthetic SSE event so the UI shows a TEXT_EXTRACTION step (UI heuristic:
    any state_delta key with a `status` field is rendered as a trace step)."""
    ok = [r for r in batch.results if r.ok]
    failed = [r for r in batch.results if not r.ok]
    findings = [f"{r.file_name}: {len(r.document_text)} chars" for r in ok]
    findings += [f"{r.file_name}: unreadable" for r in failed]
    return {
        "type": "ocr_status",
        "author": "ocr_prestage",
        "actions": {"state_delta": {"TEXT_EXTRACTION": {
            "status": "COMPLETED",
            "summary": f"Extracted text from {len(ok)}/{len(batch.results)} document(s) via self-hosted OCR.",
            "key_findings": findings[:5],
        }}},
        "claim_id": claim_id,
        "user_id": user_id,
        "session_id": session_id,
        "created_at": _now_iso(),
    }
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `cd api && uv run pytest tests/test_prestage_wiring.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Replace the image-attaching block in `claim_events`**

In `claim_events`, replace the current Content construction (main.py:341-346):
```python
        parts: list[Part] = [Part.from_text(text="Process this claim intake request:\n" + json.dumps(metadata))]
        for d in documents:
            parts.append(Part.from_bytes(data=d["bytes"], mime_type=d["mime_type"]))

        content = Content(role="user", parts=parts)
        logger.info("[SSE] claim_id=%s user_id=%s session_id=%s", claim_id, user_id, session_id)
```
with:
```python
        # OCR pre-stage: extract text from images/PDFs via the self-hosted VLM.
        # Runs off the event loop so a slow/blocking VLM call never stalls the app.
        batch = await asyncio.to_thread(extract_text_for_documents, documents)

        # Stream a synthetic TEXT_EXTRACTION step so the UI timeline is unchanged.
        yield f"data: {json.dumps(ocr_step_event(claim_id, user_id, session_id, batch))}\n\n"

        # If the OCR service was entirely unreachable, this is an outage, not a
        # member problem: route to manual review instead of asking for re-uploads.
        if batch.service_unavailable:
            await db.update_claim_final(claim_id, OCR_UNAVAILABLE_STATUS, None)
            outage_event = {
                "type": "error",
                "message": "We are processing your claim. A specialist will review it shortly.",
                "ops_detail": "OCR service unavailable — claim queued for manual review.",
                "final_status": OCR_UNAVAILABLE_STATUS,
                "claim_id": claim_id,
                "user_id": user_id,
                "session_id": session_id,
                "created_at": _now_iso(),
            }
            yield f"data: {json.dumps(outage_event)}\n\n"
            return

        content = build_agent_content(metadata, batch)
        logger.info("[SSE] claim_id=%s user_id=%s session_id=%s docs=%d", claim_id, user_id, session_id, len(documents))
```

- [ ] **Step 6: Run the full test suite**

Run: `cd api && uv run pytest -q`
Expected: PASS (all tests from Tasks 2-5).

- [ ] **Step 7: Commit**

```bash
git add api/main.py api/tests/test_prestage_wiring.py
git commit -m "feat(ocr): run OCR pre-stage and pass text-only input to the agent"
```

---

### Task 6: Strip self-OCR from the root agent (`api/agents/agent.py`)

**Files:**
- Modify: `api/agents/agent.py` (prompt lines 61-88; tools line 17, 228)

- [ ] **Step 1: Remove the `save_extracted_document_text` import and tool**

Delete the import at agent.py:17:
```python
from tools.extracted_text_store import save_extracted_document_text
```
Change the `tools=[...]` list (agent.py:228) from:
```python
    tools=[save_extracted_document_text, gate_tool, requirements_tool, extraction_tool, consistency_tool, run_policy_decision],
```
to:
```python
    tools=[gate_tool, requirements_tool, extraction_tool, consistency_tool, run_policy_decision],
```

- [ ] **Step 2: Replace the execution-order + TEXT_EXTRACTION prompt sections**

In `ROOT_PIPELINE_PROMPT`, replace the "Strict execution order" block and the entire `TEXT_EXTRACTION stage` block (agent.py:61-88) with:
```python
Strict execution order:
- DOCUMENT_CLASSIFICATION runs first. Each uploaded file already includes a
  `document_text` field that was extracted upstream by a dedicated OCR pre-stage.
  Use that text directly — do NOT attempt to read images or PDFs yourself
  (you will not receive any; you only receive text).
- Only run DOCUMENT_REQUIREMENTS next if ALL document_gate_agent results have
  `gate_outcome == "PASS"`. If any result has `gate_outcome == "PENDING_REUPLOAD"`,
  stop immediately and request reupload.
- Only run DOCUMENT_EXTRACTION if requirements outcome allows continuing.
- Only run CONSISTENCY_CHECK if extraction completed.
- Only run POLICY_DECISION if consistency check allows proceeding (PASS or
  MANUAL_REVIEW_RECOMMENDED).

Input format:
- The intake payload contains a `documents` list. Each entry has:
  file_id, file_name, mime_type, and `document_text` (already-extracted OCR text).
- If a file's `document_text` is empty or sparse, pass it as-is to
  document_gate_agent — the gate decides whether there is enough signal to classify.
  Never invent or fill in missing text.
```

- [ ] **Step 3: Verify the module still imports**

Run: `cd api && uv run python -c "from agents.agent import root_agent; print(root_agent.name)"`
Expected: prints `claims_pipeline_agent` with no import error.

- [ ] **Step 4: Run the full test suite**

Run: `cd api && uv run pytest -q`
Expected: PASS (unchanged).

- [ ] **Step 5: Commit**

```bash
git add api/agents/agent.py
git commit -m "refactor(agent): remove self-OCR stage; consume pre-extracted text"
```

---

### Task 7: Privacy invariant test + manual smoke test

**Files:**
- Create: `api/tests/test_privacy_invariant.py`
- Create: `api/ocr/README.md`

- [ ] **Step 1: Write the privacy invariant test**

Create `api/tests/test_privacy_invariant.py`:
```python
"""Guards the entire point of the OCR pre-stage: no image bytes reach the agent."""

from main import build_agent_content
from ocr.service import OcrBatchResult, OcrResult


def test_no_inline_image_data_in_agent_content():
    metadata = {"claim_id": "c1", "documents": [
        {"file_id": "F001", "file_name": "a.png", "mime_type": "image/png"},
        {"file_id": "F002", "file_name": "b.pdf", "mime_type": "application/pdf"},
    ]}
    batch = OcrBatchResult(results=[
        OcrResult("F001", "a.png", "text a", 1, True),
        OcrResult("F002", "b.pdf", "text b", 2, True),
    ])
    content = build_agent_content(metadata, batch)
    for part in content.parts:
        assert getattr(part, "inline_data", None) is None, "image bytes leaked to agent"
        assert getattr(part, "file_data", None) is None
        assert part.text is not None
```

- [ ] **Step 2: Run it to verify it passes**

Run: `cd api && uv run pytest tests/test_privacy_invariant.py -q`
Expected: PASS (1 passed).

- [ ] **Step 3: Write the OCR runbook**

Create `api/ocr/README.md`:
```markdown
# OCR Pre-Stage (self-hosted Qwen-VL)

The pre-stage runs before the Gemini orchestrator and extracts text from claim
documents so **no images are ever sent to a Gemini agent**.

## Local development (Ollama)

1. Install Ollama: https://ollama.com
2. Pull and run the VLM (7B recommended; use `:3b` if 16 GB RAM is tight):
   ```
   ollama run qwen2.5vl:7b
   ```
   Ollama serves an OpenAI-compatible API at http://localhost:11434.
3. Configure the API (defaults shown):
   ```
   OCR_BASE_URL=http://localhost:11434
   OCR_MODEL=qwen2.5vl:7b
   OCR_MAX_PDF_PAGES=10
   ```

## Production

Point `OCR_BASE_URL` at a Qwen-VL endpoint hosted inside your own GCP project
(Cloud Run + L4 GPU / GKE / Vertex). No code change — endpoint is config only.
A deployed Cloud Run backend cannot reach `localhost`.
```

- [ ] **Step 4: Manual smoke test (requires Ollama running)**

```bash
ollama run qwen2.5vl:7b          # in a separate terminal
cd api && uv run uvicorn main:app --port 8000
```
Then submit a claim with files from `mock_claim_documents/TC001/` via the UI or
`POST /claims`, open `/claims/{id}/events`, and verify:
- A `TEXT_EXTRACTION` step appears in the timeline.
- The pipeline proceeds through classification → decision using OCR'd text.
- API logs show no image parts sent to the agent.

- [ ] **Step 5: Commit**

```bash
git add api/tests/test_privacy_invariant.py api/ocr/README.md
git commit -m "test(ocr): assert privacy invariant; add OCR runbook"
```

---

## Self-Review

**Spec coverage:**
- Pre-stage placement + text-only agent input → Tasks 4, 5, 6. ✓
- `api/ocr/` package (rasterize/client/service) → Tasks 2, 3, 4. ✓
- Endpoint-configurable client (`OCR_BASE_URL`/`OCR_MODEL`) → Task 3. ✓
- PDF rasterization + page cap → Task 2. ✓
- Sequential processing → Task 4 (`extract_text_for_documents` loops serially). ✓
- Failure isolation + `PENDING_REUPLOAD` via existing gate → Task 4 (empty text flows downstream). ✓
- Whole-service-unavailable short-circuit → `MANUAL_REVIEW` → Task 5, Step 5. ✓
- Synthetic `TEXT_EXTRACTION` SSE step (UI unchanged) → Task 5. ✓
- Remove self-OCR stage + `save_extracted_document_text` tool → Task 6. ✓
- Non-hallucination OCR prompt → Task 3 (`OCR_SYSTEM_PROMPT`). ✓
- Privacy invariant test → Task 7. ✓
- Testing approach (rasterize/client/service/wiring/manual) → Tasks 2-7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `OcrResult`/`OcrBatchResult` fields used identically across Tasks 4, 5, 7; `extract_text_for_documents(documents, client=None) -> OcrBatchResult`, `OcrClient.ocr_image(bytes) -> str`, `to_images(bytes, str) -> list[bytes]`, `build_agent_content(dict, OcrBatchResult) -> Content`, `ocr_step_event(...) -> dict` consistent throughout. ✓

---

## Execution Handoff

After saving, choose execution mode (subagent-driven recommended).
