# Self-Hosted VLM OCR Pre-Stage — Design

**Date:** 2026-06-06
**Status:** Approved design, pending implementation plan
**Scope:** Move OCR out of the root Gemini orchestrator into a deterministic pre-stage backed by a self-hosted Qwen2.5-VL model (run locally via Ollama for now).

---

## Motivation

**Primary driver: data privacy.** Today the root orchestrator (Gemini 2.5 Pro) receives raw
document images as inline parts and performs OCR itself ([api/main.py:343](../../../api/main.py#L343),
[api/agents/agent.py:71-88](../../../api/agents/agent.py#L71-L88)). That sends medical document
images to a third-party LLM API.

The long-term north star is **no PHI to external LLM APIs at all**. Self-hosting OCR is the
sensible first step: it removes the most sensitive payload (the raw document images) from
Google's API, and it establishes the architectural seam that later stages (extraction,
consistency) can follow when they too move off Gemini.

This first increment self-hosts **OCR only**. Extracted text still flows to Gemini for
classification/requirements/extraction/consistency. That is an accepted, explicit interim state.

---

## Goals

- Root Gemini agent **never** receives image bytes. Images go only to the self-hosted VLM.
- OCR runs as a deterministic pre-stage before the agent is invoked.
- The OCR service endpoint is configurable so local dev (Ollama on Mac) and a future
  GCP-hosted Qwen differ only by config — no code change.
- The UI pipeline timeline is unchanged for members and staff.
- Existing non-hallucination discipline is preserved in the OCR prompt.

## Non-Goals (this increment)

- Hosting Qwen on GCP (Cloud Run GPU / GKE / Vertex). **Deferred — local dev only for now.**
- Moving extraction/consistency/decision text off Gemini.
- Fine-tuning Qwen for Indian medical documents.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| OCR placement | **Deterministic pre-stage** (not an orchestrated tool, not an LlmAgent) | Cleanest privacy boundary; images never enter any LLM Content. Generalizes to future self-hosted stages. |
| Why not an OCR LlmAgent | Rejected | Would mean Gemini calling Qwen — two models stacked for one OCR job. |
| Model host (now) | **Ollama on M4/16GB**, `qwen2.5vl:7b` (4-bit), fallback `qwen2.5vl:3b` | Fits unified memory; OpenAI-compatible API at `localhost:11434`. |
| Deployment target (now) | **Local dev only**; client endpoint-agnostic | GCP GPU hosting is a separate future milestone. |
| Concurrency | **Sequential per claim** | 16GB Mac runs one VLM inference at a time; parallel requests thrash memory. |
| PDF handling | Rasterize pages to PNG via PyMuPDF | Qwen-VL takes images; Gemini's native PDF reading is gone. |
| OCR failure model | Failures are data, not exceptions | Per-doc failure → empty text → existing gate returns `PENDING_REUPLOAD`. |

---

## Architecture & Data Flow

```
get_claim_with_documents(claim_id)          # already returns bytes + mime_type (db.py:117-122)
        │
        ▼
┌─────────────────────────────────────────────┐
│  OCR PRE-STAGE  (new — api/ocr/ package)     │
│  for each document (sequential):             │
│    • if PDF → rasterize pages to PNG (PyMuPDF)│
│    • POST image(s) → Qwen via Ollama         │
│      (OCR_BASE_URL, OpenAI-compatible)       │
│    • collect document_text (non-hallucinated)│
│  returns: list[OcrResult]                    │
└─────────────────────────────────────────────┘
        │  (text only — no bytes past here)
        ▼
emit synthetic SSE event for OCR step (UI timeline)
        │
        ▼
build Content: metadata + per-file document_text   ← NO Part.from_bytes
        │
        ▼
runner.run_async(root_agent)   # Gemini, text-only, never sees an image
```

**Privacy invariant:** *No image bytes are ever placed in a `Content` passed to any `LlmAgent`.*
This is a one-line, testable assertion and the foundation for migrating later stages off Gemini.

---

## Module Design — `api/ocr/`

```
api/ocr/
├── __init__.py
├── client.py        # OcrClient — talks to Qwen via Ollama (HTTP)
├── rasterize.py     # PDF/image bytes → list[PNG bytes]
└── service.py       # orchestrates: bytes → OcrResult per document
```

### `rasterize.py`

```python
def to_images(data: bytes, mime_type: str) -> list[bytes]:
    # image/*           → [data] unchanged
    # application/pdf   → PyMuPDF renders each page to PNG (~200 DPI)
    # cap at MAX_PDF_PAGES (default 10) to bound memory/time
```
PyMuPDF (`pymupdf`) is a pure wheel — no system deps; clean on Mac and in the container.

### `client.py`

```python
class OcrClient:
    def __init__(self,
                 base_url=os.getenv("OCR_BASE_URL", "http://localhost:11434"),
                 model=os.getenv("OCR_MODEL", "qwen2.5vl:7b"),
                 timeout=120): ...

    def ocr_image(self, png_bytes: bytes) -> str:
        # POST /v1/chat/completions (Ollama OpenAI-compatible)
        # message: image_url = data:image/png;base64,<...> + OCR system prompt
        # one retry with short backoff (covers cold model-load on first call)
        # returns raw extracted text for ONE image
```

**OCR system prompt** preserves the existing non-hallucination discipline
(currently agent.py:76-86):
- Transcribe only what is visibly present; never guess missing/blurry tokens.
- Use `[UNREADABLE]` for illegible regions; leave sparse output sparse.
- File-isolated: no cross-document context.
- Output plain text only, no commentary.

### `service.py`

```python
@dataclass
class OcrResult:
    file_id: str
    file_name: str
    document_text: str
    page_count: int
    ok: bool          # False if the OCR call errored
    error: str | None

def extract_text_for_documents(
    documents: list[dict],
    client: OcrClient | None = None,   # injectable for tests; lazy shared default
) -> list[OcrResult]:
    # for each doc: rasterize → ocr each page → join "\n\n--- page N ---\n"
    # multi-page PDFs concatenate; failures captured, not raised
```

- **Sequential** processing per claim (memory safety on the Mac).
- **Per-page join** preserves multi-page docs without merging across *files*.
- **Failures captured** as `ok=False`, not raised.

---

## Changes to Existing Code

### `api/main.py` (`claim_events`)
- After `get_claim_with_documents`, call `extract_text_for_documents(documents)`.
- Emit a synthetic SSE event for the OCR step (status, per-file char counts, failures)
  before `run_async`, so the UI timeline matches today.
- **Remove** the `Part.from_bytes` loop (main.py:342-343).
- Build the agent `Content` from metadata + per-file `document_text` (text only).
- If **all** documents failed with connection-level errors → short-circuit before the
  agent: emit SSE error event, `final_status = MANUAL_REVIEW`, ops message
  "OCR service unavailable — claim queued for manual review." Member sees a neutral
  processing state, not a false re-upload request.

### `api/agents/agent.py` (root orchestrator)
- Delete the `TEXT_EXTRACTION` stage from the prompt (lines 71-88) and the
  "extract text yourself" instruction.
- Prompt now starts at `DOCUMENT_CLASSIFICATION` using `document_text` already present per file.
- Remove `save_extracted_document_text` from the root's tools list (pre-stage owns text now).

### Dependencies
- Add `pymupdf` and an HTTP client (`httpx`, already likely present) to the API deps.

---

## Error Handling

| Failure | Behavior |
|---|---|
| One document OCRs poorly / blank scan | `ok=True`, sparse/empty text → existing gate → `PENDING_REUPLOAD`. |
| One document errors (timeout, garbled) | `ok=False`, empty text → gate → `PENDING_REUPLOAD`. |
| Corrupt/unopenable PDF | `rasterize` raises → caught → `ok=False`. |
| Huge PDF | Capped at `MAX_PDF_PAGES`; truncation noted in result. |
| First-call model load latency | One retry + generous timeout (120s). |
| **Whole OCR service unreachable** | Pre-stage short-circuits → `MANUAL_REVIEW` + ops message; **not** a member re-upload prompt. |

Mirrors the existing resilience rule (agent.py:205-207), applied at the pre-stage.

---

## Testing

- **`rasterize.py`** — fixtures: a small PDF + a PNG from `mock_claim_documents/`. Assert page
  count, valid PNG output, image passthrough unchanged.
- **`client.py`** — mock HTTP (`respx`/`responses`). Assert payload shape (base64 data URL,
  model, prompt) and that retry fires on 5xx/timeout. No real Qwen in CI.
- **`service.py`** — inject a fake `OcrClient`. Test multi-page join, per-doc failure isolation,
  all-fail short-circuit signal.
- **`main.py` wiring** — integration test with a fake service: (a) no `Part.from_bytes` reaches
  the Content, (b) synthetic OCR SSE event emitted, (c) text lands in agent input.
- **Privacy invariant test** — assert the `Content` built in `claim_events` contains zero image
  parts. Guards the whole point of the change.
- **Manual smoke test** — `ollama run qwen2.5vl:7b`, submit a real claim from
  `mock_claim_documents/`, watch end-to-end against local Qwen.

OCR *accuracy* is validated by the manual smoke test, not unit tests.

---

## Future Work (out of scope here)

- Host Qwen in GCP (Cloud Run L4 / GKE / Vertex) so the deployed app satisfies the privacy goal
  in production — `OCR_BASE_URL` points there, no code change.
- Migrate extraction/consistency/decision text off Gemini following the same pre-stage seam.
- Fine-tune / select a VLM tuned for Indian medical documents.
