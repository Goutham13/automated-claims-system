import evals.scorer as scorer
from agents.consistency_check_agent.agent import ConsistencyCheckResult
from agents.document_extraction_agent.agent import DocumentExtractionResult, PrescriptionFields
from evals.dataset import EvalCase, EvalDocument


def _case():
    return EvalCase("TC1", "c", "CONSULTATION", [EvalDocument("F1", "rx.jpg", "PRESCRIPTION", "t")])


def test_extraction_field_agreement(monkeypatch):
    ref = DocumentExtractionResult(
        file_id="F1", file_name="rx", document_type="PRESCRIPTION", extraction_confidence=0.9,
        ops_message="", prescription=PrescriptionFields(
            patient_name="Rajesh", diagnosis_primary="Fever", doctor_name="A"))
    cand = DocumentExtractionResult(
        file_id="F1", file_name="rx", document_type="PRESCRIPTION", extraction_confidence=0.9,
        ops_message="", prescription=PrescriptionFields(
            patient_name="Rajesh", diagnosis_primary="Cough", doctor_name="A"))

    def fake_extract(doc, *, backend=None, model=None):
        return ref if backend == "gemini" else cand

    monkeypatch.setattr(scorer, "extract_document", fake_extract)
    dim = scorer.ExtractionAgreementDimension(("gemini", "g"), ("ollama", "q"))
    res = dim.score([_case()])
    assert 0.0 < res.score < 1.0  # one differing field (diagnosis_primary)


def test_extraction_full_agreement(monkeypatch):
    same = DocumentExtractionResult(
        file_id="F1", file_name="rx", document_type="PRESCRIPTION", extraction_confidence=0.9,
        ops_message="", prescription=PrescriptionFields(patient_name="Rajesh"))
    monkeypatch.setattr(scorer, "extract_document", lambda doc, *, backend=None, model=None: same)
    res = scorer.ExtractionAgreementDimension(("gemini", "g"), ("ollama", "q")).score([_case()])
    assert res.score == 1.0


def test_consistency_outcome_agreement(monkeypatch):
    def fake_extract(doc, *, backend=None, model=None):
        return DocumentExtractionResult(file_id="F1", file_name="rx", document_type="PRESCRIPTION",
                                        extraction_confidence=0.9, ops_message="")

    def fake_cons(snaps, *, claimed_amount=None, treatment_date=None, backend=None, model=None):
        out = "PASS" if backend == "gemini" else "MANUAL_REVIEW_RECOMMENDED"
        return ConsistencyCheckResult(outcome=out, confidence_score=0.9, ops_message="")

    monkeypatch.setattr(scorer, "extract_document", fake_extract)
    monkeypatch.setattr(scorer, "check_consistency", fake_cons)
    res = scorer.ConsistencyAgreementDimension(("gemini", "g"), ("ollama", "q")).score([_case()])
    assert res.score == 0.0  # outcomes disagree
