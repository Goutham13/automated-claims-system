import json

from evals.reference import load_reference


def test_load_reference_roundtrip(tmp_path):
    case = {
        "ref_model": "gemini-3-pro-preview",
        "classification": {"F1": {
            "file_id": "F1", "file_name": "rx.jpg", "predicted_type": "PRESCRIPTION",
            "confidence_score": 0.95, "confidence_band": "HIGH", "gate_outcome": "PASS",
            "ops_message": "ok"}},
        "requirements": {"outcome": "PASS", "claim_category": "CONSULTATION", "ops_message": "ok"},
        "extraction": {"F1": {
            "file_id": "F1", "file_name": "rx.jpg", "document_type": "PRESCRIPTION",
            "extraction_confidence": 0.9, "ops_message": "ok"}},
        "consistency": {"outcome": "PASS", "confidence_score": 0.95, "ops_message": "ok"},
    }
    (tmp_path / "TC001.json").write_text(json.dumps(case))
    ref = load_reference(tmp_path)
    assert "TC001" in ref
    rc = ref["TC001"]
    assert rc.ref_model == "gemini-3-pro-preview"
    assert rc.classification["F1"].predicted_type == "PRESCRIPTION"
    assert rc.requirements.outcome == "PASS"
    assert rc.extraction["F1"].document_type == "PRESCRIPTION"
    assert rc.consistency.outcome == "PASS"
