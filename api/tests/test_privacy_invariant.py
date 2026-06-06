"""Guards the entire point of the OCR pre-stage: no image bytes reach the LLM pipeline."""

from main import build_documents_with_text
from ocr.service import OcrBatchResult, OcrResult


def test_pipeline_input_carries_no_image_bytes():
    documents = [
        {"file_id": "F001", "file_name": "a.png", "mime_type": "image/png", "bytes": b"\x89PNG..."},
        {"file_id": "F002", "file_name": "b.pdf", "mime_type": "application/pdf", "bytes": b"%PDF..."},
    ]
    batch = OcrBatchResult(results=[
        OcrResult("F001", "a.png", "text a", 1, True),
        OcrResult("F002", "b.pdf", "text b", 2, True),
    ])
    out = build_documents_with_text(documents, batch)
    for item in out:
        assert set(item.keys()) == {"file_id", "file_name", "document_text"}
        assert "bytes" not in item and "mime_type" not in item
    assert out[0]["document_text"] == "text a"
