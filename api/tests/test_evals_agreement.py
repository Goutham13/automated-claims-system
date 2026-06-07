import evals.scorer as scorer
from agents.consistency_check_agent.agent import ConsistencyCheckResult
from agents.document_extraction_agent.agent import DocumentExtractionResult, PrescriptionFields
from evals.dataset import EvalCase, EvalDocument
from evals.reference import RefCase


def _case():
    return EvalCase("TC1", "c", "CONSULTATION", [EvalDocument("F1", "rx.jpg", "PRESCRIPTION", "t")])


def _ext(diag):
    return DocumentExtractionResult(
        file_id="F1", file_name="rx", document_type="PRESCRIPTION", extraction_confidence=0.9,
        ops_message="", prescription=PrescriptionFields(
            patient_name="Rajesh", diagnosis_primary=diag, doctor_name="A"))


def _ref_case(ext, cons_outcome="PASS"):
    return {"TC1": RefCase(
        classification={}, requirements=None, extraction={"F1": ext},
        consistency=ConsistencyCheckResult(outcome=cons_outcome, confidence_score=0.9, ops_message=""),
        ref_model="gemini-3-pro-preview")}


def test_extraction_field_agreement_vs_cached(monkeypatch):
    reference = _ref_case(_ext("Fever"))
    monkeypatch.setattr(scorer, "extract_document",
                        lambda doc, *, backend=None, model=None: _ext("Cough"))  # one field differs
    res = scorer.ExtractionAgreementDimension(("ollama", "q"), reference).score([_case()])
    assert 0.0 < res.score < 1.0


def test_extraction_full_agreement_vs_cached(monkeypatch):
    reference = _ref_case(_ext("Fever"))
    monkeypatch.setattr(scorer, "extract_document",
                        lambda doc, *, backend=None, model=None: _ext("Fever"))
    res = scorer.ExtractionAgreementDimension(("ollama", "q"), reference).score([_case()])
    assert res.score == 1.0


def test_consistency_outcome_agreement_vs_cached(monkeypatch):
    reference = _ref_case(_ext("Fever"), cons_outcome="PASS")

    def fake_cons(snaps, *, claimed_amount=None, treatment_date=None, backend=None, model=None):
        return ConsistencyCheckResult(outcome="MANUAL_REVIEW_RECOMMENDED", confidence_score=0.9, ops_message="")

    monkeypatch.setattr(scorer, "check_consistency", fake_cons)
    res = scorer.ConsistencyAgreementDimension(("ollama", "q"), reference).score([_case()])
    assert res.score == 0.0  # candidate disagrees with cached PASS
