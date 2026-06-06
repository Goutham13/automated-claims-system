import pipeline.stages as st
from agents.document_extraction_agent.agent import (
    DocumentExtractionResult,
    HospitalBillFields,
    PrescriptionFields,
)


def test_build_snapshots_maps_fields():
    results = [
        DocumentExtractionResult(
            file_id="F1",
            file_name="rx",
            document_type="PRESCRIPTION",
            extraction_confidence=0.9,
            ops_message="",
            prescription=PrescriptionFields(
                patient_name="Rajesh",
                prescription_date="2024-11-01",
                diagnosis_primary="Viral Fever",
                doctor_name="Dr A",
                hospital_or_clinic_name="City Clinic",
            ),
        ),
        DocumentExtractionResult(
            file_id="F2",
            file_name="bill",
            document_type="HOSPITAL_BILL",
            extraction_confidence=0.9,
            ops_message="",
            hospital_bill=HospitalBillFields(
                patient_name="Rajesh",
                bill_date="2024-11-01",
                total_amount=4200.0,
                hospital_name="City Hospital",
                referring_doctor_name="Dr A",
            ),
        ),
    ]
    snaps = st.build_consistency_snapshots(results)
    assert snaps[0].patient_name == "Rajesh"
    assert snaps[0].primary_date == "2024-11-01"
    assert snaps[0].diagnosis == "Viral Fever"
    assert snaps[0].doctor_name == "Dr A"
    assert snaps[0].provider_name == "City Clinic"
    assert snaps[1].amount == 4200.0
    assert snaps[1].provider_name == "City Hospital"


def test_classify_passes_through_llm_result(monkeypatch):
    from agents.document_gate_agent.agent import DocumentClassificationResult

    captured = {}

    def fake_call(prompt, payload, output_model, **kw):
        captured["prompt"] = prompt
        captured["output_model"] = output_model
        return DocumentClassificationResult(
            file_id="F1", file_name="x", predicted_type="PRESCRIPTION",
            confidence_score=0.95, confidence_band="HIGH", gate_outcome="PASS", ops_message="ok",
        )

    monkeypatch.setattr(st, "structured_llm_call", fake_call)
    r = st.classify_document({"file_id": "F1", "file_name": "x", "document_text": "t"})
    assert r.predicted_type == "PRESCRIPTION" and r.gate_outcome == "PASS"
    assert captured["output_model"] is DocumentClassificationResult
    assert "classifier" in captured["prompt"].lower()


def test_classify_error_returns_pending_reupload(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(st, "structured_llm_call", boom)
    r = st.classify_document({"file_id": "F1", "file_name": "x", "document_text": "t"})
    assert r.gate_outcome == "PENDING_REUPLOAD"
    assert r.predicted_type == "UNKNOWN"


def test_consistency_error_returns_blocked(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(st, "structured_llm_call", boom)
    r = st.check_consistency([])
    assert r.outcome == "BLOCKED"
