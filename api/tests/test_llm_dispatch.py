import pipeline.llm as llm
from pydantic import BaseModel


class Out(BaseModel):
    label: str


def test_dispatch_to_ollama(monkeypatch):
    monkeypatch.setenv("PIPELINE_BACKEND", "ollama")
    called = {}
    monkeypatch.setattr(llm, "_ollama_call", lambda *a, **k: called.__setitem__("ollama", True) or Out(label="o"))
    monkeypatch.setattr(llm, "_gemini_call", lambda *a, **k: called.__setitem__("gemini", True) or Out(label="g"))
    out = llm.structured_llm_call("sys", {"x": 1}, Out)
    assert out.label == "o" and called == {"ollama": True}


def test_dispatch_to_gemini_by_default(monkeypatch):
    monkeypatch.delenv("PIPELINE_BACKEND", raising=False)
    monkeypatch.setattr(llm, "_gemini_call", lambda *a, **k: Out(label="g"))
    monkeypatch.setattr(llm, "_ollama_call", lambda *a, **k: Out(label="o"))
    assert llm.structured_llm_call("sys", {"x": 1}, Out).label == "g"
