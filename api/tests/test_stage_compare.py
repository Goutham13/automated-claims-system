from evals.scorer import DimensionResult
from evals.stage_compare import build_stage_report, render_stage_markdown


def _lat(ms):
    return {"mean_ms": ms, "median_ms": ms, "p95_ms": ms}


def _report():
    cls_cand = DimensionResult("classification", 0.92, {"accuracy": 0.92, "latency": _lat(5600)})
    cls_ref = {"accuracy": 0.96, "correct": 23, "total": 24}
    req_cand = DimensionResult("requirements", 0.9, {"accuracy": 0.9, "latency": _lat(650)})
    req_ref = {"accuracy": 1.0, "correct": 12, "total": 12}
    ex = DimensionResult("extraction", 0.85, {
        "mean_field_agreement": 0.85, "exact_only": 0.6, "critical_field_agreement": 0.92,
        "ref_completeness": 1.0, "cand_completeness": 0.9, "cand_latency": _lat(1100)})
    co = DimensionResult("consistency", 0.83, {"outcome_agreement": 0.83, "cand_latency": _lat(750)})
    return build_stage_report(cls_cand, cls_ref, req_cand, req_ref, ex, co,
                              "gemini-3-pro-preview", ("ollama", "qwen2.5:14b"))


def test_build_stage_report_has_all_stages():
    rep = _report()
    assert set(rep["stages"]) == {"classification", "requirements", "extraction", "consistency"}
    assert rep["cand"]["model"] == "qwen2.5:14b"
    assert rep["ref_model"] == "gemini-3-pro-preview"
    assert rep["stages"]["classification"]["ref"]["accuracy"] == 0.96
    assert rep["stages"]["extraction"]["mean_field_agreement"] == 0.85


def test_render_stage_markdown():
    md = render_stage_markdown(_report())
    assert "qwen2.5:14b" in md and "gemini-3-pro-preview" in md
    assert "classification" in md and "consistency" in md
    assert "latency" in md.lower()
