"""Typed understanding stages — each is ONE structured LLM call reusing existing prompts/schemas.

The orchestrator imports these as module-level names so tests can monkeypatch them. Each stage
isolates LLM failures: a raised error becomes that stage's safe stop outcome, never a crash.
"""

from __future__ import annotations

import json

from agents.consistency_check_agent.agent import (
    CONSISTENCY_CHECK_PROMPT,
    ConsistencyCheckInput,
    ConsistencyCheckResult,
    DocumentConsistencySnapshot,
)
from agents.document_extraction_agent.agent import (
    DOCUMENT_EXTRACTION_PROMPT,
    DocumentExtractionResult,
    ExtractionInputDocument,
)
from agents.document_gate_agent.agent import (
    DOCUMENT_GATE_PROMPT,
    DocumentClassificationResult,
    UploadedDocumentInput,
)
from agents.document_requirements_agent.agent import (
    DOCUMENT_REQUIREMENTS_PROMPT,
    DocumentRequirementsInput,
    DocumentRequirementsResult,
)
from pipeline.llm import structured_llm_call


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def classify_document(doc: dict) -> DocumentClassificationResult:
    payload = UploadedDocumentInput(
        file_id=doc["file_id"],
        file_name=doc["file_name"],
        document_text=doc.get("document_text", ""),
    )
    try:
        return structured_llm_call(DOCUMENT_GATE_PROMPT, payload, DocumentClassificationResult)
    except Exception as exc:
        return DocumentClassificationResult(
            file_id=doc["file_id"],
            file_name=doc["file_name"],
            predicted_type="UNKNOWN",
            confidence_score=0.0,
            confidence_band="LOW",
            gate_outcome="PENDING_REUPLOAD",
            ops_message=f"Classification failed: {exc}",
        )


def check_requirements(claim_category: str, predicted_types: list[str]) -> DocumentRequirementsResult:
    payload = DocumentRequirementsInput(claim_category=claim_category, predicted_types=predicted_types)
    try:
        return structured_llm_call(DOCUMENT_REQUIREMENTS_PROMPT, payload, DocumentRequirementsResult)
    except Exception as exc:
        return DocumentRequirementsResult(
            outcome="BLOCKED",
            claim_category=claim_category,
            ops_message=f"Requirements check failed: {exc}",
        )


def extract_document(doc: dict) -> DocumentExtractionResult:
    payload = ExtractionInputDocument(
        file_id=doc["file_id"],
        file_name=doc["file_name"],
        document_type=doc["document_type"],
        document_text=doc.get("document_text", ""),
    )
    try:
        return structured_llm_call(DOCUMENT_EXTRACTION_PROMPT, payload, DocumentExtractionResult)
    except Exception as exc:
        return DocumentExtractionResult(
            file_id=doc["file_id"],
            file_name=doc["file_name"],
            document_type=doc["document_type"],
            extraction_confidence=0.0,
            missing_critical_fields=["ALL"],
            ops_message=f"Extraction failed: {exc}",
        )


def build_consistency_snapshots(
    results: list[DocumentExtractionResult],
) -> list[DocumentConsistencySnapshot]:
    """Deterministic field mapping from each extraction result to a consistency snapshot."""
    snaps: list[DocumentConsistencySnapshot] = []
    for r in results:
        rx, hb, lab, ph, dn, ds = (
            r.prescription,
            r.hospital_bill,
            r.lab_report,
            r.pharmacy_bill,
            r.dental_report,
            r.discharge_summary,
        )
        snaps.append(
            DocumentConsistencySnapshot(
                file_id=r.file_id,
                file_name=r.file_name,
                document_type=r.document_type,
                patient_name=_first(
                    *(getattr(x, "patient_name", None) for x in (rx, hb, lab, ph, dn, ds))
                ),
                primary_date=_first(
                    getattr(rx, "prescription_date", None),
                    getattr(hb, "bill_date", None),
                    getattr(lab, "report_date", None),
                    getattr(ph, "bill_date", None),
                    getattr(ds, "discharge_date", None),
                ),
                amount=_first(
                    getattr(hb, "total_amount", None),
                    getattr(ph, "net_amount", None),
                ),
                diagnosis=_first(
                    getattr(rx, "diagnosis_primary", None),
                    getattr(dn, "diagnosis", None),
                    getattr(ds, "final_diagnosis", None),
                ),
                provider_name=_first(
                    getattr(rx, "hospital_or_clinic_name", None),
                    getattr(hb, "hospital_name", None),
                    getattr(lab, "lab_name", None),
                    getattr(ph, "pharmacy_name", None),
                ),
                doctor_name=_first(
                    getattr(rx, "doctor_name", None),
                    getattr(hb, "referring_doctor_name", None),
                    getattr(lab, "referring_doctor_name", None),
                ),
            )
        )
    return snaps


def check_consistency(
    snapshots: list[DocumentConsistencySnapshot],
    *,
    claimed_amount: float | None = None,
    treatment_date: str | None = None,
) -> ConsistencyCheckResult:
    payload = ConsistencyCheckInput(
        claimed_amount=claimed_amount,
        treatment_date=treatment_date,
        extracted_documents=json.dumps([s.model_dump() for s in snapshots]),
    )
    try:
        return structured_llm_call(CONSISTENCY_CHECK_PROMPT, payload, ConsistencyCheckResult)
    except Exception as exc:
        return ConsistencyCheckResult(
            outcome="BLOCKED",
            confidence_score=0.0,
            ops_message=f"Consistency check failed: {exc}",
        )
