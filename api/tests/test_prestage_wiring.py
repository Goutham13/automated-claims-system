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
