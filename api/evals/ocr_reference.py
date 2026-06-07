"""Capture Gemini-3-pro OCR over the test-case document images (reference for OCR comparison).

This is a multimodal genai call (image in, plain text out) — separate from the text-only pipeline
call-site. Output is committed so `ocr_compare` can run without re-spending pro.

Run from api/ (needs Vertex):
  OCR_REF_MODEL=gemini-3-pro-preview python -m evals.ocr_reference
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from google import genai
from google.genai.types import GenerateContentConfig, Part

from evals.dataset import TEST_CASES, resolve_doc_file

OCR_REFERENCE_DIR = Path(__file__).resolve().parent / "reference_ocr"

_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

_OCR_PROMPT = (
    "Transcribe ALL text from this medical document image verbatim. "
    "Output only the transcribed plain text — no commentary, no markdown. "
    "Do not guess unreadable text; use [UNREADABLE] for illegible regions."
)


def capture_ocr_reference() -> None:
    model = os.getenv("OCR_REF_MODEL", "gemini-2.5-pro")
    client = genai.Client()
    data = json.loads(TEST_CASES.read_text())
    for case in data["test_cases"]:
        cid = case["case_id"]
        out = OCR_REFERENCE_DIR / cid
        out.mkdir(parents=True, exist_ok=True)
        for d in case["input"]["documents"]:
            p = resolve_doc_file(cid, d)
            if not p:
                print(f"[skip] {cid} {d['file_id']}: no file")
                continue
            contents = [
                Part.from_bytes(data=p.read_bytes(),
                                mime_type=_MIME.get(p.suffix.lower(), "image/jpeg")),
                _OCR_PROMPT,
            ]
            text = None
            for attempt in range(4):  # tolerate transient 503/timeouts
                try:
                    resp = client.models.generate_content(
                        model=model, contents=contents,
                        config=GenerateContentConfig(temperature=0.0))
                    text = resp.text or ""
                    break
                except Exception as exc:
                    if attempt == 3:
                        print(f"[{cid}] {d['file_id']}: FAILED after retries: {str(exc)[:80]}")
                        text = "[OCR_FAILED]"
                    else:
                        time.sleep(3 * (attempt + 1))
            (out / f"{d['file_id']}.txt").write_text(text or "")
            print(f"[{cid}] {d['file_id']}: {len(text or '')} chars")


if __name__ == "__main__":
    capture_ocr_reference()
