import evals.scorer as scorer
from agents.document_gate_agent.agent import DocumentClassificationResult
from evals.dataset import EvalCase, EvalDocument


def _doc(fid, actual):
    return EvalDocument(fid, f"{fid}.jpg", actual, ocr_text="text")


def _result(ptype, gate="PASS"):
    return DocumentClassificationResult(
        file_id="x", file_name="x", predicted_type=ptype, confidence_score=0.9,
        confidence_band="HIGH", gate_outcome=gate, ops_message="")


def test_classification_accuracy_and_confusion(monkeypatch):
    cases = [EvalCase("TC1", "c", "CONSULTATION",
                      [_doc("F1", "PRESCRIPTION"), _doc("F2", "HOSPITAL_BILL")])]
    preds = {"F1": _result("PRESCRIPTION"), "F2": _result("PRESCRIPTION")}  # F2 wrong
    monkeypatch.setattr(scorer, "classify_document", lambda d: preds[d["file_id"]])
    res = scorer.ClassificationDimension().score(cases)
    assert res.name == "classification"
    assert res.score == 0.5
    assert res.details["correct"] == 1 and res.details["total"] == 2
    assert res.details["confusion"]["HOSPITAL_BILL"]["PRESCRIPTION"] == 1


def test_gate_false_negative_counted(monkeypatch):
    cases = [EvalCase("TC1", "c", "CONSULTATION", [_doc("F1", "PRESCRIPTION")])]
    monkeypatch.setattr(scorer, "classify_document",
                        lambda d: _result("UNKNOWN", gate="PENDING_REUPLOAD"))
    res = scorer.ClassificationDimension().score(cases)
    assert res.details["gate_false_negatives"] == 1
