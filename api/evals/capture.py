"""One-time: run the self-hosted OCR over each test case's documents, save text fixtures.

Run from api/ with Ollama serving the OCR model:

    python -m evals.capture

Fixtures are committed so eval runs need only the classifier backend (no Ollama).
"""

from __future__ import annotations

import json

from evals.dataset import FIXTURES, TEST_CASES, resolve_doc_file
from ocr.service import extract_text_for_documents

_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def capture() -> None:
    data = json.loads(TEST_CASES.read_text())
    for c in data["test_cases"]:
        cid = c["case_id"]
        out = FIXTURES / cid
        out.mkdir(parents=True, exist_ok=True)
        docs = []
        for d in c["input"]["documents"]:
            p = resolve_doc_file(cid, d)
            if not p:
                print(f"[skip] {cid} {d['file_id']}: no file found")
                continue
            docs.append({
                "file_id": d["file_id"],
                "file_name": p.name,
                "mime_type": _MIME.get(p.suffix.lower(), "image/jpeg"),
                "bytes": p.read_bytes(),
            })
        batch = extract_text_for_documents(docs)
        for r in batch.results:
            (out / f"{r.file_id}.txt").write_text(r.document_text)
            status = "ok" if r.ok else f"FAIL: {r.error}"
            print(f"[{cid}] {r.file_id}: {len(r.document_text)} chars {status}")


if __name__ == "__main__":
    capture()
