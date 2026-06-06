import fitz  # PyMuPDF
import pytest

from ocr.rasterize import to_images, MAX_PDF_PAGES


def _make_pdf(num_pages: int) -> bytes:
    doc = fitz.open()
    for _ in range(num_pages):
        page = doc.new_page()
        page.insert_text((72, 72), "Hello claim")
    data = doc.tobytes()
    doc.close()
    return data


def _png_magic(b: bytes) -> bool:
    return b[:8] == b"\x89PNG\r\n\x1a\n"


def test_image_passthrough_unchanged():
    raw = b"\x89PNG\r\n\x1a\n-fake-image-bytes"
    assert to_images(raw, "image/png") == [raw]
    assert to_images(raw, "image/jpeg") == [raw]


def test_pdf_one_image_per_page():
    pdf = _make_pdf(3)
    images = to_images(pdf, "application/pdf")
    assert len(images) == 3
    assert all(_png_magic(img) for img in images)


def test_pdf_page_cap():
    pdf = _make_pdf(MAX_PDF_PAGES + 5)
    images = to_images(pdf, "application/pdf")
    assert len(images) == MAX_PDF_PAGES


def test_corrupt_pdf_raises():
    with pytest.raises(Exception):
        to_images(b"not a real pdf", "application/pdf")
