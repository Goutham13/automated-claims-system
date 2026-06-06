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
