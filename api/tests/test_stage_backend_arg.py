import pipeline.llm as llm
import pipeline.stages as stages
from agents.document_gate_agent.agent import DocumentClassificationResult


def test_structured_call_explicit_backend(monkeypatch):
    calls = {}

    def fake_ollama(sp, payload, om, *, model=None, base_url=None, retries=1):
        calls["backend"] = "ollama"
        calls["model"] = model
        return om.model_construct()

    monkeypatch.setattr(llm, "_ollama_call", fake_ollama)
    monkeypatch.delenv("PIPELINE_BACKEND", raising=False)
    llm.structured_llm_call("s", {"a": 1}, DocumentClassificationResult,
                            backend="ollama", model="qwen2.5:7b-instruct")
    assert calls["backend"] == "ollama" and calls["model"] == "qwen2.5:7b-instruct"


def test_stage_forwards_backend(monkeypatch):
    seen = {}

    def fake_call(sp, payload, om, *, model=None, backend=None, client=None):
        seen["backend"] = backend
        seen["model"] = model
        return om.model_construct(
            file_id="F1", file_name="x", predicted_type="PRESCRIPTION",
            confidence_score=1.0, confidence_band="HIGH", gate_outcome="PASS", ops_message="")

    monkeypatch.setattr(stages, "structured_llm_call", fake_call)
    stages.classify_document({"file_id": "F1", "file_name": "x", "document_text": "t"},
                             backend="gemini", model="gemini-3-flash-preview")
    assert seen["backend"] == "gemini" and seen["model"] == "gemini-3-flash-preview"
