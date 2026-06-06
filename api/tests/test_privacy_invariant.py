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
