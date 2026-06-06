from pydantic import BaseModel

from pipeline.llm import structured_llm_call


class Out(BaseModel):
    label: str
    score: float


class FakeModels:
    def __init__(self, parsed):
        self._parsed = parsed
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)

        class R:
            pass

        r = R()
        r.parsed = self._parsed
        r.text = self._parsed.model_dump_json() if self._parsed is not None else ""
        return r


class FakeClient:
    def __init__(self, parsed):
        self.models = FakeModels(parsed)


def test_structured_call_returns_parsed_model():
    client = FakeClient(Out(label="PRESCRIPTION", score=0.9))
    out = structured_llm_call("sys", {"document_text": "x"}, Out, client=client)
    assert isinstance(out, Out) and out.label == "PRESCRIPTION"
    cfg = client.models.calls[0]["config"]
    assert cfg.response_schema is Out
    assert cfg.response_mime_type == "application/json"
    assert cfg.system_instruction == "sys"


def test_falls_back_to_text_when_parsed_missing():
    class M:
        def generate_content(self, **k):
            class R:
                pass

            r = R()
            r.parsed = None
            r.text = '{"label":"HOSPITAL_BILL","score":0.5}'
            return r

    class C:
        models = M()

    out = structured_llm_call("sys", {"a": 1}, Out, client=C())
    assert out.label == "HOSPITAL_BILL" and out.score == 0.5
