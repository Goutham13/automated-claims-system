"""Compare self-hosted VLM OCR vs Gemini-3-pro OCR (text similarity; no gold transcription).

Pro OCR is treated as the stronger reference; we report how closely the local VLM OCR agrees with it.

Run from api/ (after `python -m evals.ocr_reference` has captured pro OCR):
  python -m evals.ocr_compare
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from evals.dataset import FIXTURES, load_cases
from evals.ocr_reference import OCR_REFERENCE_DIR

RESULTS = Path(__file__).resolve().parent / "results"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def similarity(a: str, b: str) -> dict[str, float]:
    """Char-ratio (difflib) + token Jaccard on normalized text, plus char-count delta."""
    na, nb = _normalize(a), _normalize(b)
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jaccard = (len(ta & tb) / len(ta | tb)) if (ta or tb) else 1.0
    return {
        "char_ratio": round(ratio, 3),
        "token_jaccard": round(jaccard, 3),
        "vlm_chars": len(a),
        "pro_chars": len(b),
    }


@dataclass
class OcrPair:
    case_id: str
    file_id: str
    vlm_text: str
    pro_text: str


def _load_pairs() -> list[OcrPair]:
    pairs: list[OcrPair] = []
    for case in load_cases():
        for doc in case.documents:
            vlm_path = FIXTURES / case.case_id / f"{doc.file_id}.txt"
            pro_path = OCR_REFERENCE_DIR / case.case_id / f"{doc.file_id}.txt"
            if not vlm_path.exists() or not pro_path.exists():
                continue
            pairs.append(OcrPair(case.case_id, doc.file_id,
                                 vlm_path.read_text(), pro_path.read_text()))
    return pairs


def build_report(pairs: list[OcrPair]) -> dict:
    rows = []
    ratios, jaccards = [], []
    for p in pairs:
        sim = similarity(p.vlm_text, p.pro_text)
        ratios.append(sim["char_ratio"])
        jaccards.append(sim["token_jaccard"])
        rows.append({"case_id": p.case_id, "file_id": p.file_id, **sim})
    n = len(rows) or 1
    return {
        "comparison": "vlm_ocr_vs_claude_opus_4_8_ocr",
        "docs": len(rows),
        "mean_char_ratio": round(sum(ratios) / n, 3),
        "mean_token_jaccard": round(sum(jaccards) / n, 3),
        "rows": sorted(rows, key=lambda r: r["char_ratio"]),
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# OCR comparison — VLM (`qwen2.5vl-ocr`) vs Claude Opus 4.8 OCR (reference)",
        f"Docs: {report['docs']} · mean char-ratio {report['mean_char_ratio']:.1%} · "
        f"mean token-Jaccard {report['mean_token_jaccard']:.1%}",
        "",
        "Most-divergent documents:",
        "| case | file | char-ratio | token-Jaccard | vlm/pro chars |",
        "|---|---|---|---|---|",
    ]
    for r in report["rows"][:8]:
        lines.append(f"| {r['case_id']} | {r['file_id']} | {r['char_ratio']:.1%} | "
                     f"{r['token_jaccard']:.1%} | {r['vlm_chars']}/{r['pro_chars']} |")
    return "\n".join(lines)


def main() -> None:
    pairs = _load_pairs()
    if not pairs:
        raise SystemExit("No OCR pairs. Run `python -m evals.ocr_reference` and ensure fixtures exist.")
    report = build_report(pairs)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "ocr_compare.json").write_text(json.dumps(report, indent=2))
    print(render_markdown(report))
    print(f"\nWrote {RESULTS / 'ocr_compare.json'}")


if __name__ == "__main__":
    main()
