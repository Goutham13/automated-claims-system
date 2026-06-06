from evals.report import build_result, compare, render_markdown
from evals.scorer import DimensionResult


def _result(model, rows):
    dr = DimensionResult(
        "classification",
        sum(r["correct"] for r in rows) / len(rows),
        {"rows": rows, "total": len(rows), "correct": sum(r["correct"] for r in rows)},
    )
    return build_result([dr], model)


def test_build_and_render():
    res = _result("gemini", [{"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION",
                              "predicted": "PRESCRIPTION", "correct": True}])
    assert res["model"] == "gemini"
    assert res["dimensions"]["classification"]["score"] == 1.0
    md = render_markdown(res)
    assert "classification" in md and "gemini" in md


def test_compare_flags_regression_and_improvement():
    base = _result("gemini", [
        {"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION", "predicted": "PRESCRIPTION", "correct": True},
        {"case_id": "TC2", "file_id": "F2", "actual": "LAB_REPORT", "predicted": "UNKNOWN", "correct": False}])
    new = _result("qwen", [
        {"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION", "predicted": "UNKNOWN", "correct": False},
        {"case_id": "TC2", "file_id": "F2", "actual": "LAB_REPORT", "predicted": "LAB_REPORT", "correct": True}])
    diff = compare(new, base)
    assert any(d["file_id"] == "F1" for d in diff["regressions"])
    assert any(d["file_id"] == "F2" for d in diff["improvements"])
