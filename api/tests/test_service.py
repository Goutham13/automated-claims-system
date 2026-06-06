from ocr.client import OcrUnavailableError
from ocr.service import extract_text_for_documents


def _doc(file_id: str, mime: str = "image/png", data: bytes = b"\x89PNG\r\n\x1a\nx"):
    return {"file_id": file_id, "file_name": f"{file_id}.png", "mime_type": mime, "bytes": data}


class FakeClient:
    def __init__(self, mapping=None, raise_unavailable=False):
        self.mapping = mapping or {}
        self.raise_unavailable = raise_unavailable
        self.calls = 0

    def ocr_image(self, png_bytes: bytes) -> str:
        self.calls += 1
        if self.raise_unavailable:
            raise OcrUnavailableError("down")
        return self.mapping.get(png_bytes, "DEFAULT TEXT")


def test_single_image_success():
    batch = extract_text_for_documents([_doc("F001")], client=FakeClient())
    assert batch.service_unavailable is False
    assert len(batch.results) == 1
    r = batch.results[0]
    assert r.ok and r.file_id == "F001" and r.page_count == 1
    assert r.document_text == "DEFAULT TEXT"


def test_multi_page_pdf_join(monkeypatch):
    # Force rasterize to yield two pages without a real PDF.
    monkeypatch.setattr("ocr.service.to_images", lambda data, mime: [b"p1", b"p2"])
    client = FakeClient(mapping={b"p1": "PAGE ONE", b"p2": "PAGE TWO"})
    doc = {"file_id": "F002", "file_name": "bill.pdf", "mime_type": "application/pdf", "bytes": b"%PDF"}
    batch = extract_text_for_documents([doc], client=client)
    r = batch.results[0]
    assert r.page_count == 2
    assert "PAGE ONE" in r.document_text and "PAGE TWO" in r.document_text


def test_one_doc_failure_isolated(monkeypatch):
    def boom(data, mime):
        if mime == "application/pdf":
            raise ValueError("corrupt")
        return [b"img"]
    monkeypatch.setattr("ocr.service.to_images", boom)
    docs = [_doc("F001"), {"file_id": "F002", "file_name": "x.pdf",
                           "mime_type": "application/pdf", "bytes": b"bad"}]
    batch = extract_text_for_documents(docs, client=FakeClient())
    assert batch.service_unavailable is False
    by_id = {r.file_id: r for r in batch.results}
    assert by_id["F001"].ok is True
    assert by_id["F002"].ok is False and by_id["F002"].document_text == ""


def test_all_fail_unavailable_short_circuit():
    docs = [_doc("F001"), _doc("F002")]
    batch = extract_text_for_documents(docs, client=FakeClient(raise_unavailable=True))
    assert batch.service_unavailable is True
    assert all(r.ok is False for r in batch.results)
