from evals.ocr_compare import build_report, render_markdown, similarity
from evals.ocr_compare import OcrPair


def test_similarity_identical():
    s = similarity("Dr. Sharma  Fever", "dr. sharma fever")
    assert s["char_ratio"] == 1.0
    assert s["token_jaccard"] == 1.0


def test_similarity_divergent():
    s = similarity("PRESCRIPTION paracetamol", "completely different lab report values")
    assert s["char_ratio"] < 0.5
    assert s["token_jaccard"] < 0.5


def test_build_and_render_report():
    pairs = [
        OcrPair("TC1", "F1", "patient rajesh fever", "patient rajesh fever"),
        OcrPair("TC2", "F2", "abc", "xyz totally different text here"),
    ]
    rep = build_report(pairs)
    assert rep["docs"] == 2
    assert 0.0 <= rep["mean_char_ratio"] <= 1.0
    # rows sorted ascending by char_ratio → most divergent first
    assert rep["rows"][0]["case_id"] == "TC2"
    md = render_markdown(rep)
    assert "OCR comparison" in md and "char-ratio" in md
