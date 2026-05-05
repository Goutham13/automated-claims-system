"""Cross-document consistency check agent for claim processing."""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, Field

MODEL = "gemini-3-flash-preview"

Severity = Literal["INFO", "WARNING", "BLOCKER"]
ConsistencyOutcome = Literal["PASS", "BLOCKED", "MANUAL_REVIEW_RECOMMENDED"]


class DocumentConsistencySnapshot(BaseModel):
    """Flattened key fields from one DocumentExtractionResult, sufficient for consistency checks."""

    file_id: str
    file_name: str
    document_type: str = Field(description="Document type from classification, e.g. PRESCRIPTION.")
    patient_name: str | None = Field(
        default=None,
        description="Patient name as it appears in this document.",
    )
    primary_date: str | None = Field(
        default=None,
        description=(
            "Main date on this document in YYYY-MM-DD: prescription_date, bill_date, "
            "sample_date, report_date, etc. — whichever is populated."
        ),
    )
    amount: float | None = Field(
        default=None,
        description="Primary monetary amount: hospital_bill.total_amount or pharmacy_bill.net_amount.",
    )
    diagnosis: str | None = Field(
        default=None,
        description="Primary diagnosis or procedure: prescription.diagnosis_primary, dental_report.diagnosis, etc.",
    )
    provider_name: str | None = Field(
        default=None,
        description="Hospital, clinic, lab, or pharmacy name from this document.",
    )
    doctor_name: str | None = Field(
        default=None,
        description="Treating or prescribing doctor name from this document.",
    )


class ConsistencyCheckInput(BaseModel):
    claimed_amount: float | None = None
    treatment_date: str | None = Field(
        default=None,
        description="Claim-level treatment date in YYYY-MM-DD.",
    )
    extracted_documents: str = Field(
        default="[]",
        description=(
            "JSON-serialised list of DocumentConsistencySnapshot objects, one per document. "
            "Each object has: file_id, file_name, document_type, patient_name, primary_date, "
            "amount, diagnosis, provider_name, doctor_name. "
            "Do NOT re-parse or re-infer values — only compare the pre-extracted fields."
        ),
    )


class ConsistencyIssue(BaseModel):
    issue_code: str = Field(
        description="Stable issue code, e.g. PATIENT_NAME_MISMATCH, DATE_MISMATCH, AMOUNT_MISMATCH."
    )
    severity: Severity
    description: str
    affected_file_names: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(
        default_factory=list,
        description="Concrete values from the snapshot fields that conflict, e.g. ['Rajesh Kumar (F001)', 'Arjun Mehta (F002)'].",
    )


class ConsistencyCheckResult(BaseModel):
    outcome: ConsistencyOutcome
    confidence_score: float = Field(description="0.0–1.0 confidence in the consistency decision.")
    ops_message: str
    key_findings: list[str] = Field(default_factory=list)
    issues: list[ConsistencyIssue] = Field(default_factory=list)


CONSISTENCY_CHECK_PROMPT = """
You are a cross-document consistency checker for health insurance claims.

Input:
- treatment_date: the date entered by the member when submitting the claim.
- claimed_amount: the amount entered by the member.
- extracted_documents: a JSON string containing a list of DocumentConsistencySnapshot objects.
  Parse the JSON to get the list. Each snapshot has typed, pre-extracted fields —
  do NOT re-derive or re-infer values. Trust the fields as given; only compare them.

Your job is to compare field values across documents and surface contradictions.
Do not re-extract or guess — only use the values already present in the snapshots.

---
Checks to perform (in order):

1. PATIENT IDENTITY (BLOCKER if mismatch)
   - Compare patient_name across all snapshots that have it non-null.
   - A clear name mismatch (e.g. "Rajesh Kumar" vs "Arjun Mehta") is a BLOCKER.
   - Minor formatting differences (initials, abbreviations) are INFO only.
   - Evidence: list each ("name (file_name)") pair that conflicts.

2. DATE CONSISTENCY (BLOCKER or WARNING)
   - Compare each snapshot's primary_date against treatment_date.
   - A mismatch of more than 3 days is a BLOCKER if it appears in a primary document
     (PRESCRIPTION or HOSPITAL_BILL); WARNING for supporting documents.
   - Evidence: list ("YYYY-MM-DD (file_name)") for each conflicting date.

3. AMOUNT CONSISTENCY (WARNING)
   - Compare amount values (where non-null) against claimed_amount.
   - If the total from bills exceeds claimed_amount by more than 10%, raise WARNING.
   - Evidence: list amount values and claimed_amount.

4. PROVIDER / DOCTOR CROSS-REFERENCE (INFO or WARNING)
   - If multiple documents reference a doctor_name or provider_name, check they refer
     to the same entity (allowing for abbreviations).
   - A clear mismatch (entirely different names/hospitals) is a WARNING.

5. DIAGNOSIS / PROCEDURE ALIGNMENT (WARNING)
   - If diagnosis is present in multiple documents, check for consistency.
   - A prescription for "dental cleaning" alongside a bill for "cardiac surgery" is a WARNING.

---
Outcome rules:
- BLOCKED: any BLOCKER issue.
- MANUAL_REVIEW_RECOMMENDED: no BLOCKER but at least one WARNING.
- PASS: no issues or INFO only.

Output requirements:
- ops_message: name the specific conflicting values — never generic.
- key_findings: concise bullets of what was compared and what was found.
- issues: one entry per distinct problem, with evidence as concrete value pairs.
"""


consistency_check_agent = LlmAgent(
    model=MODEL,
    name="consistency_check_agent",
    description=(
        "Validates cross-document consistency for identity, dates, amounts, and providers "
        "using structured extraction snapshots; returns BLOCKED/MANUAL_REVIEW_RECOMMENDED/PASS."
    ),
    instruction=CONSISTENCY_CHECK_PROMPT,
    generate_content_config=GenerateContentConfig(
        temperature=0.1,
        top_p=1.0,
        top_k=1.0,
    ),
    input_schema=ConsistencyCheckInput,
    output_schema=ConsistencyCheckResult,
    output_key="consistency_check_result",
)
