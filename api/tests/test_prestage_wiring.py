from main import (
    OCR_UNAVAILABLE_STATUS,
    build_documents_with_text,
    ocr_step_event,
    pipeline_event_to_sse,
)
from ocr.service import OcrBatchResult, OcrResult


def _docs():
    return [{"file_id": "F001", "file_name": "bill.png", "mime_type": "image/png", "bytes": b"x"}]


def test_build_documents_with_text_injects_ocr_text():
    batch = OcrBatchResult(results=[OcrResult("F001", "bill.png", "PHARMACY BILL", 1, True)])
    out = build_documents_with_text(_docs(), batch)
    assert out == [{"file_id": "F001", "file_name": "bill.png", "document_text": "PHARMACY BILL"}]


def test_ocr_step_event_shape():
    batch = OcrBatchResult(results=[OcrResult("F001", "bill.png", "abc", 1, True)])
    event = ocr_step_event("c1", "u1", "s1", batch)
    step = event["actions"]["state_delta"]["TEXT_EXTRACTION"]
    assert step["status"] == "COMPLETED"
    assert "key_findings" in step


def test_pipeline_event_to_sse_wraps_state_delta():
    ev = {
        "type": "stage",
        "step_name": "DOCUMENT_CLASSIFICATION",
        "state_delta": {"DOCUMENT_CLASSIFICATION": {"status": "COMPLETED"}},
    }
    sse = pipeline_event_to_sse(ev, "c1", "u1", "s1")
    assert sse["actions"]["state_delta"] == ev["state_delta"]
    assert sse["claim_id"] == "c1" and sse["author"] == "claims_pipeline_agent"


def test_unavailable_status_constant():
    assert OCR_UNAVAILABLE_STATUS == "MANUAL_REVIEW"
