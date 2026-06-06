"""Load eval cases: test_cases.json ground truth joined with captured OCR fixtures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1]  # api/
_REPO = _API_DIR.parent  # repo root
TEST_CASES = _REPO / "test_cases.json"
MOCK_DIR = _REPO / "mock_claim_documents"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

IMG_EXTS = (".jpg", ".jpeg", ".png")


@dataclass
class EvalDocument:
    file_id: str
    file_name: str
    actual_type: str
    ocr_text: str = ""


@dataclass
class EvalCase:
    case_id: str
    case_name: str
    claim_category: str
    documents: list[EvalDocument]


def resolve_doc_file(case_id: str, doc: dict) -> Path | None:
    """Find the image file for a document: by file_name, else by file_id prefix."""
    case_dir = MOCK_DIR / case_id
    if not case_dir.is_dir():
        return None
    fn = doc.get("file_name")
    if fn and (case_dir / fn).exists():
        return case_dir / fn
    fid = doc["file_id"]
    for p in sorted(case_dir.iterdir()):
        if p.suffix.lower() in IMG_EXTS and p.stem.startswith(fid):
            return p
    return None


def load_cases() -> list[EvalCase]:
    data = json.loads(TEST_CASES.read_text())
    cases: list[EvalCase] = []
    for c in data["test_cases"]:
        docs: list[EvalDocument] = []
        for d in c["input"]["documents"]:
            fid = d["file_id"]
            resolved = resolve_doc_file(c["case_id"], d)
            fname = d.get("file_name") or (resolved.name if resolved else fid)
            fx = FIXTURES / c["case_id"] / f"{fid}.txt"
            text = fx.read_text() if fx.exists() else ""
            docs.append(EvalDocument(fid, fname, d["actual_type"], text))
        cases.append(EvalCase(c["case_id"], c["case_name"], c["input"]["claim_category"], docs))
    return cases
