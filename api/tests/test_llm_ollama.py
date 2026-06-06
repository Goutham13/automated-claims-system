import httpx
import pytest
import respx
from pydantic import BaseModel

import pipeline.llm as llm


class Out(BaseModel):
    label: str
    score: float


def _resp(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@respx.mock
def test_ollama_parses_and_sends_json_object(monkeypatch):
    monkeypatch.setenv("PIPELINE_BASE_URL", "http://test-llm")
    monkeypatch.setenv("PIPELINE_MODEL", "qwen2.5vl-ocr")
    route = respx.post("http://test-llm/v1/chat/completions").mock(
        return_value=_resp('{"label":"PRESCRIPTION","score":0.9}'))
    out = llm._ollama_call("classify", {"document_text": "x"}, Out)
    assert out.label == "PRESCRIPTION" and out.score == 0.9
    body = route.calls.last.request.content.decode()
    assert "json_object" in body
    assert "qwen2.5vl-ocr" in body
    assert "schema" in body.lower()


@respx.mock
def test_ollama_retries_once_then_raises(monkeypatch):
    monkeypatch.setenv("PIPELINE_BASE_URL", "http://test-llm")
    monkeypatch.setenv("PIPELINE_MODEL", "m")
    route = respx.post("http://test-llm/v1/chat/completions").mock(return_value=_resp("not json"))
    with pytest.raises(Exception):
        llm._ollama_call("sys", {"x": 1}, Out)
    assert route.call_count == 2


@respx.mock
def test_ollama_retry_recovers(monkeypatch):
    monkeypatch.setenv("PIPELINE_BASE_URL", "http://test-llm")
    monkeypatch.setenv("PIPELINE_MODEL", "m")
    respx.post("http://test-llm/v1/chat/completions").mock(side_effect=[
        _resp("garbage"), _resp('{"label":"L","score":0.1}')])
    out = llm._ollama_call("sys", {"x": 1}, Out)
    assert out.label == "L"
