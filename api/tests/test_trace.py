from pipeline.trace import (
    PipelineStepResult,
    PipelineTrace,
    final_state_delta,
    stage_state_delta,
)


def test_stage_state_delta_shape():
    d = stage_state_delta("DOCUMENT_CLASSIFICATION", "COMPLETED", "ok", ["a", "b"])
    step = d["DOCUMENT_CLASSIFICATION"]
    assert step["status"] == "COMPLETED"
    assert step["summary"] == "ok"
    assert step["key_findings"] == ["a", "b"]


def test_final_state_delta_carries_summary_keys():
    trace = PipelineTrace(
        steps=[PipelineStepResult(step_name="POLICY_DECISION", status="COMPLETED", summary="done")],
        final_status="APPROVED",
        final_member_message="m",
        final_ops_summary="o",
    )
    d = final_state_delta(trace)
    assert d["final_status"] == "APPROVED"
    assert d["final_member_message"] == "m"
    assert d["final_ops_summary"] == "o"
    assert d["policy_decision"] is None
    assert d["POLICY_DECISION"]["status"] == "COMPLETED"
