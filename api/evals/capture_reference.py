"""Build the Gemini golden-set reference once: run the reference model over all stages, commit it.

Run from api/ (needs Vertex):
  REF_MODEL=gemini-3-pro-preview python -m evals.capture_reference

Reference is used as the gold for the label-less stages (extraction, consistency); pro's own
classification/requirements outputs are stored too (for its accuracy-vs-truth column).
Stage-isolated inputs: OCR fixtures + ground-truth actual_type (same as stage_compare).
"""

from __future__ import annotations

import json
import os

from evals.dataset import load_cases
from evals.reference import REFERENCE_DIR
from pipeline.stages import (
    build_consistency_snapshots,
    check_consistency,
    check_requirements,
    classify_document,
    extract_document,
)


def capture_reference() -> None:
    model = os.getenv("REF_MODEL", "gemini-3-pro-preview")
    backend = "gemini"
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    cases = load_cases()
    total_docs = err_docs = 0
    for case in cases:
        classification: dict[str, dict] = {}
        extraction: dict[str, dict] = {}
        extraction_results = []
        for doc in case.documents:
            d = {"file_id": doc.file_id, "file_name": doc.file_name, "document_text": doc.ocr_text}
            classification[doc.file_id] = classify_document(d, backend=backend, model=model).model_dump()
            ext = extract_document({**d, "document_type": doc.actual_type}, backend=backend, model=model)
            extraction[doc.file_id] = ext.model_dump()
            extraction_results.append(ext)

        actual_types = [doc.actual_type for doc in case.documents]
        requirements = check_requirements(case.claim_category, actual_types, backend=backend, model=model)
        snaps = build_consistency_snapshots(extraction_results)
        consistency = check_consistency(snaps, backend=backend, model=model)

        payload = {
            "ref_model": model,
            "classification": classification,
            "requirements": requirements.model_dump(),
            "extraction": extraction,
            "consistency": consistency.model_dump(),
        }
        (REFERENCE_DIR / f"{case.case_id}.json").write_text(json.dumps(payload, indent=2))
        errs = sum(1 for e in extraction.values() if "failed:" in (e.get("ops_message") or "").lower())
        total_docs += len(extraction)
        err_docs += errs
        print(f"[{case.case_id}] reference captured ({len(case.documents)} docs"
              + (f", {errs} extraction error(s)" if errs else "") + ")")

    # Systematic failure (e.g. wrong model id) → abort. Isolated errors (e.g. an
    # intentionally-unreadable doc) are expected and kept as-is.
    if total_docs and err_docs / total_docs > 0.5:
        raise SystemExit(
            f"Reference model '{model}' failed on {err_docs}/{total_docs} docs — likely a bad "
            f"REF_MODEL or auth issue. Fix and re-run; the golden set must be real outputs.")
    if err_docs:
        print(f"\nNote: {err_docs}/{total_docs} docs errored (expected for unreadable/edge docs).")


if __name__ == "__main__":
    capture_reference()
