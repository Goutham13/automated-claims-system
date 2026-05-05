"""Per-file document classification agent for claim intake (text-only)."""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, Field

MODEL = "gemini-2.5-flash"

DocumentType = Literal[
    "PRESCRIPTION",
    "HOSPITAL_BILL",
    "LAB_REPORT",
    "PHARMACY_BILL",
    "DENTAL_REPORT",
    "DISCHARGE_SUMMARY",
    "UNKNOWN",
]

ConfidenceBand = Literal["HIGH", "MEDIUM", "LOW"]
GateOutcome = Literal["PASS", "PENDING_REUPLOAD"]


class UploadedDocumentInput(BaseModel):
    file_id: str = Field(description="Unique file id from client.")
    file_name: str = Field(description="Original uploaded file name.")
    document_text: str = Field(description="Plain text extracted from the document (OCR-style).")


class DocumentClassificationResult(BaseModel):
    file_id: str = Field(description="Echoed file id.")
    file_name: str = Field(description="Echoed file name.")
    predicted_type: DocumentType = Field(description="Type predicted by classifier from actual file content.")
    confidence_score: float = Field(description="0.0-1.0 confidence score for predicted type.")
    confidence_band: ConfidenceBand = Field(description="HIGH, MEDIUM, LOW confidence bucket.")
    extracted_signals: list[str] = Field(
        default_factory=list,
        description="Short evidence snippets from the text that support the classification decision.",
    )
    missing_required_signals: list[str] = Field(
        default_factory=list,
        description=(
            "Required classification signals that are absent from the text. "
            "List only the signals that are mandatory to confirm the predicted type. "
            "Empty list means all required signals are present."
        ),
    )
    gate_outcome: GateOutcome = Field(
        description=(
            "PASS if the text contains enough required signals to confirm the document type. "
            "PENDING_REUPLOAD if too many required signals are absent — meaning the document "
            "cannot be reliably classified and must be re-uploaded as a clear, legible copy."
        )
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Concise, high-signal classification highlights for UI step progress.",
    )
    ops_message: str = Field(
        description="Concise operations message for pipeline trace."
    )


DOCUMENT_GATE_PROMPT = """
You are a per-file medical document classifier for health insurance claims.

Purpose:
- Classify a single document into one document type using ONLY the provided `document_text`.
- Decide whether the text contains enough evidence to confirm the classification (gate_outcome).

Model constraints:
- You receive only extracted text — NOT the original image or PDF.
- Classify using key text cues (headers, fields, tables, totals, result ranges, etc.).
- Never infer signals that are not present in the text. Only list signals you can actually see.

Output format:
- Return ONLY valid JSON matching the provided schema.
- Return exactly one classification result for the provided file.
- Always provide `ops_message` and `key_findings`.

Document type definitions and REQUIRED signals:

1) PRESCRIPTION:
- Strong cues: doctor name or registration number, diagnosis or chief complaint,
  at least one medicine with dose/frequency.
- REQUIRED signals (need at least 2 of 3): doctor identifier, diagnosis/complaint, medicine entry.
- Registration patterns: KA/XXXXX/YYYY, MH/XXXXX/YYYY, DL/XXXXX/YYYY, TN/XXXXX/YYYY, etc.

2) HOSPITAL_BILL:
- Strong cues: bill/invoice/receipt header, bill number or bill date, patient name,
  itemized services or amounts, subtotal or total.
- REQUIRED signals (need at least 2 of 3): bill/invoice identifier, patient name, monetary amount or line items.

3) LAB_REPORT:
- Strong cues: test name, result value, reference range or unit, lab name, report date.
- REQUIRED signals (need at least 2 of 3): test name with result, lab identifier, report/sample date.

4) PHARMACY_BILL:
- Strong cues: pharmacy/store header, drug license number, medicine rows with batch/expiry/qty/MRP,
  net amount, pharmacist stamp.
- REQUIRED signals (need at least 2 of 3): pharmacy identifier, at least one medicine entry, monetary amount.

5) DENTAL_REPORT:
- Strong cues: dental terms (caries, root canal, extraction, crown, filling), dentist name.
- REQUIRED signals (need at least 2 of 2): dental procedure or diagnosis term, dentist or clinic identifier.

6) DISCHARGE_SUMMARY:
- Strong cues: admission date, discharge date, final diagnosis, treatment summary, hospital header.
- REQUIRED signals (need at least 2 of 3): admission/discharge dates, final diagnosis, hospital identifier.

Confidence band guidance:
- HIGH (>= 0.80): All required signals present and unambiguous.
- MEDIUM (0.50–0.79): Most required signals present; minor gaps or ambiguity.
- LOW (< 0.50): Significant signals missing; classification is a best guess.

Gate outcome rules (REQUIRED — follow exactly):
- gate_outcome = PENDING_REUPLOAD if ANY of:
    - confidence_band == "LOW" (too few signals to be certain of document type), OR
    - The text is mostly empty, garbled, or filled with [UNREADABLE] placeholders, OR
    - predicted_type == "UNKNOWN" (text gives no usable classification signal).
- gate_outcome = PASS if confidence_band is "HIGH" or "MEDIUM" and required signals are present.
- CRITICAL: Do NOT set gate_outcome = PASS just because you can guess the type from one or two words.
  A classification without sufficient supporting signals is not usable for claim processing.

Missing required signals:
- List only signals that are mandatory for the predicted_type and genuinely absent from the text.
- If the text is too sparse to find any signals, list the full set of required signals as missing.

ops_message when gate_outcome = PENDING_REUPLOAD:
- Name the specific signals that are missing so the pipeline trace is actionable.
"""


document_gate_agent = LlmAgent(
    model=MODEL,
    name="document_gate_agent",
    description=(
        "Classifies a single uploaded claim document into a document type "
        "and decides whether the extracted text contains sufficient signals to proceed."
    ),
    instruction=DOCUMENT_GATE_PROMPT,
    generate_content_config=GenerateContentConfig(
        temperature=0.1,
        top_p=1.0,
        top_k=1.0,
    ),
    input_schema=UploadedDocumentInput,
    output_schema=DocumentClassificationResult,
    output_key="document_gate_result",
)
