from evals.report import build_result, compare, render_markdown
from evals.scorer import DimensionResult


def _result(model, rows, latency=None):
    details = {"rows": rows, "total": len(rows), "correct": sum(r["correct"] for r in rows)}
    if latency:
        details["latency"] = latency
    dr = DimensionResult(
        "classification",
        sum(r["correct"] for r in rows) / len(rows),
        details,
    )
    return build_result([dr], model)


def test_build_and_render():
    res = _result("gemini", [{"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION",
                              "predicted": "PRESCRIPTION", "correct": True}],
                  latency={"mean_ms": 120.0, "median_ms": 110.0, "p95_ms": 200.0})
    assert res["model"] == "gemini"
    assert res["dimensions"]["classification"]["score"] == 1.0
    md = render_markdown(res)
    assert "classification" in md and "gemini" in md
    assert "latency" in md and "120" in md


def test_compare_includes_latency_delta():
    base = _result("gemini", [{"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION",
                               "predicted": "PRESCRIPTION", "correct": True}],
                   latency={"mean_ms": 100.0, "median_ms": 90.0, "p95_ms": 150.0})
    new = _result("qwen", [{"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION",
                            "predicted": "PRESCRIPTION", "correct": True}],
                  latency={"mean_ms": 800.0, "median_ms": 750.0, "p95_ms": 1200.0})
    diff = compare(new, base)
    assert diff["latency_delta"]["baseline_mean_ms"] == 100.0
    assert diff["latency_delta"]["new_mean_ms"] == 800.0


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
