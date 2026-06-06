import httpx
import pytest
import respx

from ocr.client import OcrClient, OcrUnavailableError

PNG = b"\x89PNG\r\n\x1a\n-img"


def _ok_response(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@respx.mock
def test_ocr_image_returns_text_and_sends_data_url():
    route = respx.post("http://test-ocr/v1/chat/completions").mock(
        return_value=_ok_response("PHARMACY BILL\nTotal 420")
    )
    client = OcrClient(base_url="http://test-ocr", model="qwen2.5vl:7b")
    text = client.ocr_image(PNG)

    assert text == "PHARMACY BILL\nTotal 420"
    sent = route.calls.last.request
    body = sent.content.decode()
    assert "qwen2.5vl:7b" in body
    assert "data:image/png;base64," in body


@respx.mock
def test_retry_then_success_on_5xx():
    route = respx.post("http://test-ocr/v1/chat/completions").mock(
        side_effect=[httpx.Response(503), _ok_response("ok")]
    )
    client = OcrClient(base_url="http://test-ocr", retry_backoff=0)
    assert client.ocr_image(PNG) == "ok"
    assert route.call_count == 2


@respx.mock
def test_connection_error_raises_unavailable():
    respx.post("http://test-ocr/v1/chat/completions").mock(
        side_effect=httpx.ConnectError("refused")
    )
    client = OcrClient(base_url="http://test-ocr", retry_backoff=0)
    with pytest.raises(OcrUnavailableError):
        client.ocr_image(PNG)
