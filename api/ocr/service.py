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
