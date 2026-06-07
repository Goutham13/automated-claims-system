import evals.scorer as scorer
from agents.document_requirements_agent.agent import DocumentRequirementsResult
from evals.dataset import EvalCase, EvalDocument
from evals.scorer import RequirementsDimension, _expected_requirements


def _doc(fid, t):
    return EvalDocument(fid, f"{fid}.jpg", t, "txt")


def test_expected_requirements_rules():
    assert _expected_requirements("CONSULTATION", ["PRESCRIPTION", "HOSPITAL_BILL"]) == "PASS"
    assert _expected_requirements("CONSULTATION", ["PRESCRIPTION", "PRESCRIPTION"]) == "NOT_PASS"
    assert _expected_requirements("PHARMACY", ["PRESCRIPTION", "PHARMACY_BILL"]) == "PASS"
    assert _expected_requirements("DENTAL", ["HOSPITAL_BILL"]) == "PASS"
    assert _expected_requirements("DIAGNOSTIC", ["PRESCRIPTION", "HOSPITAL_BILL"]) == "NOT_PASS"


def test_requirements_dimension_scores_each_model(monkeypatch):
    cases = [EvalCase("TC1", "c", "CONSULTATION",
                      [_doc("F1", "PRESCRIPTION"), _doc("F2", "HOSPITAL_BILL")])]

    def fake_req(cat, types, *, backend=None, model=None):
        outcome = "PASS" if backend == "gemini" else "PENDING_REUPLOAD"
        return DocumentRequirementsResult(outcome=outcome, claim_category=cat, ops_message="")

    monkeypatch.setattr(scorer, "check_requirements", fake_req)
    dim = RequirementsDimension(("gemini", "gemini-x"), ("ollama", "qwen"))
    res = dim.score(cases)
    assert res.details["ref"]["accuracy"] == 1.0   # gemini -> PASS == expected PASS
    assert res.details["cand"]["accuracy"] == 0.0   # candidate -> NOT_PASS != expected PASS
