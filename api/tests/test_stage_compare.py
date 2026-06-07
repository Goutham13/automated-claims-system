from evals.scorer import DimensionResult
from evals.stage_compare import build_stage_report, render_stage_markdown


def _lat(ms):
    return {"mean_ms": ms, "median_ms": ms, "p95_ms": ms}


def _report():
    cl_ref = DimensionResult("classification", 0.96, {"accuracy": 0.96, "latency": _lat(5800)})
    cl_cand = DimensionResult("classification", 0.92, {"accuracy": 0.92, "latency": _lat(5600)})
    rq = DimensionResult("requirements", 0.9, {
        "ref": {"accuracy": 1.0, "latency": _lat(700)},
        "cand": {"accuracy": 0.9, "latency": _lat(650)}})
    ex = DimensionResult("extraction", 0.85, {
        "mean_field_agreement": 0.85, "ref_completeness": 1.0, "cand_completeness": 0.9,
        "ref_latency": _lat(900), "cand_latency": _lat(1100)})
    co = DimensionResult("consistency", 0.83, {
        "outcome_agreement": 0.83, "ref_latency": _lat(800), "cand_latency": _lat(750)})
    return build_stage_report(cl_ref, cl_cand, rq, ex, co,
                              ("gemini", "gemini-3-flash-preview"), ("ollama", "qwen2.5:7b-instruct"))


def test_build_stage_report_has_all_stages():
    rep = _report()
    assert set(rep["stages"]) == {"classification", "requirements", "extraction", "consistency"}
    assert rep["cand"]["model"] == "qwen2.5:7b-instruct"
    assert rep["stages"]["extraction"]["mean_field_agreement"] == 0.85


def test_render_stage_markdown():
    md = render_stage_markdown(_report())
    assert "qwen2.5:7b-instruct" in md and "gemini-3-flash-preview" in md
    assert "classification" in md and "consistency" in md
    assert "Latency" in md
