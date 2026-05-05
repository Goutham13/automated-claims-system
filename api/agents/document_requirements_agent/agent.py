"""Claim-level document requirements validator (after per-file classification)."""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, Field

MODEL = "gemini-3-flash-preview"

ClaimCategory = Literal[
    "CONSULTATION",
    "DIAGNOSTIC",
    "PHARMACY",
    "DENTAL",
    "VISION",
    "ALTERNATIVE_MEDICINE",
]

DocumentType = Literal[
    "PRESCRIPTION",
    "HOSPITAL_BILL",
    "LAB_REPORT",
    "PHARMACY_BILL",
    "DENTAL_REPORT",
    "DISCHARGE_SUMMARY",
    "UNKNOWN",
]

RequirementsOutcome = Literal["PASS", "BLOCKED", "PENDING_REUPLOAD"]


class DocumentRequirementsInput(BaseModel):
    claim_category: ClaimCategory
    predicted_types: list[DocumentType] = Field(
        default=[],
        description="List of per-file predicted document types from DOCUMENT_CLASSIFICATION (may include duplicates).",
    )


class DocumentRequirementsResult(BaseModel):
    outcome: RequirementsOutcome
    claim_category: ClaimCategory
    required_types: list[DocumentType] = Field(default_factory=list)
    missing_required_types: list[DocumentType] = Field(default_factory=list)
    ops_message: str
    key_findings: list[str] = Field(default_factory=list, description="Short bullets for pipeline trace highlights.")


DOCUMENT_REQUIREMENTS_PROMPT = """
You are the Document Requirements Validator for a health insurance claim intake flow.

Inputs you will receive in the user message:
- claim_category: one of CONSULTATION, DIAGNOSTIC, PHARMACY, DENTAL, VISION, ALTERNATIVE_MEDICINE
- predicted_types: list of per-file predicted document types (strings), may include duplicates and UNKNOWN.

Your job:
- Decide whether the required combination of documents has been received for the claim_category.

Document requirements (use exactly these rules):

CONSULTATION:
  required: PRESCRIPTION, HOSPITAL_BILL
  optional: LAB_REPORT

DIAGNOSTIC:
  required: PRESCRIPTION, LAB_REPORT, HOSPITAL_BILL
  optional: DISCHARGE_SUMMARY

PHARMACY:
  required: PRESCRIPTION, PHARMACY_BILL
  optional: (none)

DENTAL:
  required: HOSPITAL_BILL
  optional: PRESCRIPTION, DENTAL_REPORT

VISION:
  required: PRESCRIPTION, HOSPITAL_BILL
  optional: (none)

ALTERNATIVE_MEDICINE:
  required: PRESCRIPTION, HOSPITAL_BILL
  optional: (none)

Outcome rules:
- PASS: all required types are satisfied.
- PENDING_REUPLOAD: any required type is missing.
- BLOCKED: use only when the upload set is clearly wrong and cannot proceed without correction.
  Example: the member uploaded multiple documents, but none can satisfy any required type due to clear non-overlap.
  In most cases prefer PENDING_REUPLOAD with specific guidance.

ops_message requirements:
- Name missing required document types explicitly.
- If member uploaded duplicates of another type while a required type is missing, say so plainly using counts:
  Example: 'Received 2 PRESCRIPTION documents but no HOSPITAL_BILL.'
- If UNKNOWN appears in predicted_types, note the unreadable/unclear document(s).

Return ONLY valid JSON matching the output schema.
"""


document_requirements_agent = LlmAgent(
    model=MODEL,
    name="document_requirements_agent",
    description="Validates that required claim documents are present for the claim category.",
    instruction=DOCUMENT_REQUIREMENTS_PROMPT,
    generate_content_config=GenerateContentConfig(
        temperature=0.1,
        top_p=1.0,
        top_k=1.0,
    ),
    input_schema=DocumentRequirementsInput,
    output_schema=DocumentRequirementsResult,
    output_key="document_requirements_result",
)
