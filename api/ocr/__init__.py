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
