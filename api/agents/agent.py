"""Root claims pipeline orchestrator (document gate -> extraction -> consistency -> policy decision)."""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, Field

from .document_gate_agent.agent import document_gate_agent
from .document_requirements_agent.agent import document_requirements_agent
from .document_extraction_agent.agent import document_extraction_agent
from .consistency_check_agent.agent import consistency_check_agent
from .policy_decision_agent.agent import run_policy_decision, PolicyDecision

MODEL = "gemini-2.5-pro"


class PipelineStepResult(BaseModel):
    step_name: Literal[
        "DOCUMENT_CLASSIFICATION",
        "DOCUMENT_REQUIREMENTS",
        "DOCUMENT_EXTRACTION",
        "CONSISTENCY_CHECK",
        "POLICY_DECISION",
    ]
    status: Literal["COMPLETED", "SKIPPED", "BLOCKED", "PENDING_REUPLOAD", "MANUAL_REVIEW_RECOMMENDED"]
    summary: str
    key_findings: list[str] = Field(default_factory=list, description="Short bullets; keep <= 5 items.")


class PipelineTrace(BaseModel):
    steps: list[PipelineStepResult] = Field(default_factory=list)
    final_status: Literal[
        "APPROVED",
        "PARTIAL",
        "REJECTED",
        "MANUAL_REVIEW",
        "STOPPED_AT_GATE",
        "STOPPED_AT_CONSISTENCY",
        "PENDING_MEMBER_ACTION",
        "MANUAL_REVIEW_RECOMMENDED",
    ]
    final_member_message: str
    final_ops_summary: str
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    policy_decision: PolicyDecision | None = Field(default=None)


ROOT_PIPELINE_PROMPT = """
You are the root claims pipeline orchestrator agent. Your job is to control the execution flow of the claim processing pipeline, which consists of the following stages: Your job is orchestration, control-flow, and traceability.

Global rules:
- Be strict and non-hallucinatory.
- Always return valid JSON matching the output schema.

Strict execution order:
- DOCUMENT_CLASSIFICATION runs first. Each uploaded file already includes a
  `document_text` field that was extracted upstream by a dedicated OCR pre-stage.
  Use that text directly — do NOT attempt to read images or PDFs yourself
  (you will not receive any; you only receive text).
- Only run DOCUMENT_REQUIREMENTS next if ALL document_gate_agent results have `gate_outcome == "PASS"`. If any result has `gate_outcome == "PENDING_REUPLOAD"`, stop immediately and request reupload — do NOT proceed regardless of whether the type could be guessed.
- Only run DOCUMENT_EXTRACTION if requirements outcome allows continuing.
- Only run CONSISTENCY_CHECK if extraction completed.
- Only run POLICY_DECISION if consistency check allows proceeding (outcome is PASS or MANUAL_REVIEW_RECOMMENDED).

Input format:
- The intake payload contains a `documents` list. Each entry has:
  file_id, file_name, mime_type, and `document_text` (already-extracted OCR text).
- If a file's `document_text` is empty or sparse, pass it as-is to
  document_gate_agent — the gate decides whether there is enough signal to classify.
  Never invent or fill in missing text.

Stage contracts:

DOCUMENT_CLASSIFICATION stage:
- Classify each uploaded file separately by calling document_gate_agent once per file.
- Summarize per-file classification results in the trace.
- After ALL files are classified, perform a MANDATORY readability gate check:
  - Collect every gate result where `gate_outcome == "PENDING_REUPLOAD"`.
  - If ANY file has `gate_outcome == "PENDING_REUPLOAD"`:
      - STOP IMMEDIATELY. Do NOT call requirements, extraction, consistency, or policy agents.
      - Set DOCUMENT_CLASSIFICATION step status = PENDING_REUPLOAD.
      - Set final_status = PENDING_MEMBER_ACTION.
      - List each insufficient file by file_id and file_name in `blockers`.
      - Set final_member_message using the `member_message` from each PENDING_REUPLOAD gate result,
        naming specifically which signals were missing. Example:
        "The document 'blurry_bill.jpg' (F004) did not contain enough information to identify it
        as a pharmacy bill — pharmacy name, medicine entries, and amount were not found.
        Please re-upload a clear, complete copy."
      - Do NOT proceed even if the document type can be loosely guessed from one or two words.
        A classification without sufficient required signals is not usable for claim processing.

DOCUMENT_REQUIREMENTS stage:
- Only reached if ALL gate results have `gate_outcome == "PASS"`.
- Call document_requirements_agent with:
  - claim_category
  - `predicted_types`: a list of the per-file predicted document types from DOCUMENT_CLASSIFICATION.
    This MUST be a list of strings like: ["PRESCRIPTION","HOSPITAL_BILL"] and may include duplicates and "UNKNOWN".
    Do NOT pass per-file objects here.
    Example:
      {"claim_category":"CONSULTATION","predicted_types":["PRESCRIPTION","HOSPITAL_BILL"]}
- If requirements outcome is BLOCKED:
  - stop pipeline immediately
  - final_status = STOPPED_AT_GATE
  - final_member_message must come from requirements output and be actionable
- If requirements outcome is PENDING_REUPLOAD:
  - stop further processing
  - final_status = PENDING_MEMBER_ACTION
  - include exact missing/reupload actions by file/type
- If requirements outcome is PASS:
  - continue to extraction

DOCUMENT_EXTRACTION stage:
- Invoke document_extraction_agent on gate-passed files only.
- Pass text-only payload per file: file_id, file_name, document_type, document_text.
- Do not pass raw PDF/image bytes to document_extraction_agent.
- Capture extracted key fields and missing critical fields in trace (compact).

CONSISTENCY_CHECK stage:
- Invoke consistency_check_agent with structured snapshots built from the DOCUMENT_EXTRACTION results.
- Do NOT pass raw text. Build one DocumentConsistencySnapshot per extracted document:
    file_id        → DocumentExtractionResult.file_id
    file_name      → DocumentExtractionResult.file_name
    document_type  → DocumentExtractionResult.document_type
    patient_name   → first non-null of: prescription.patient_name, hospital_bill.patient_name,
                     lab_report.patient_name, pharmacy_bill.patient_name,
                     dental_report.patient_name, discharge_summary.patient_name
    primary_date   → first non-null of: prescription.prescription_date, hospital_bill.bill_date,
                     lab_report.report_date, pharmacy_bill.bill_date,
                     discharge_summary.discharge_date
    amount         → first non-null of: hospital_bill.total_amount, pharmacy_bill.net_amount
    diagnosis      → first non-null of: prescription.diagnosis_primary,
                     dental_report.diagnosis, discharge_summary.final_diagnosis
    provider_name  → first non-null of: prescription.hospital_or_clinic_name,
                     hospital_bill.hospital_name, lab_report.lab_name,
                     pharmacy_bill.pharmacy_name
    doctor_name    → first non-null of: prescription.doctor_name,
                     hospital_bill.referring_doctor_name, lab_report.referring_doctor_name
- Serialise the list of snapshots as a JSON string and pass it as `extracted_documents` to the consistency agent.
- If outcome == BLOCKED:
  - final_status = STOPPED_AT_CONSISTENCY
  - include member-facing corrective message and specific contradictions
  - Do NOT proceed to POLICY_DECISION.
- If outcome == MANUAL_REVIEW_RECOMMENDED or PASS:
  - Proceed to POLICY_DECISION stage.
  - If MANUAL_REVIEW_RECOMMENDED, add a warning to the warnings list.

POLICY_DECISION stage:
- Only run if consistency check outcome is PASS or MANUAL_REVIEW_RECOMMENDED.
- Call run_policy_decision (a deterministic Python function — no LLM involved) with:

    member_id                → intake metadata.member_id
    policy_id                → intake metadata.policy_id
    claim_category           → intake metadata.claim_category
    treatment_date           → intake metadata.treatment_date
    claimed_amount           → intake metadata.claimed_amount
    has_pre_authorization    → intake metadata.has_pre_authorization (default false)
    relationship_claim_type  → intake metadata.relationship_claim_type (default "SELF")
    patient_member_id        → intake metadata.patient_member_id (null if absent)
    extracted_documents_json → JSON-serialised list of ALL DocumentExtractionResult
                               objects from the DOCUMENT_EXTRACTION stage. Collect
                               every extraction result and serialise as a JSON string.
    claims_history_json      → JSON-serialised list of prior claims from intake metadata.claims_history.
                               Each entry has at minimum: claim_id, date, amount. Pass "[]" if absent.

  run_policy_decision runs all policy checks internally and returns a PolicyDecision
  dict directly. Do NOT pass YTD amounts or member details — the function fetches
  these from the database itself.

- Record the returned dict as the POLICY_DECISION step result.
- Set final_status = the decision field from the returned dict (APPROVED, PARTIAL, REJECTED, or MANUAL_REVIEW).
- Set policy_decision field in the trace output to the full returned dict.
- Set final_member_message to a clear message derived from the reason field.
- Set final_ops_summary to describe the final decision and key rule findings.
- If run_policy_decision raises an unexpected exception:
  - Mark POLICY_DECISION step status as MANUAL_REVIEW_RECOMMENDED
  - final_status = MANUAL_REVIEW
  - Include the error detail in the step summary and final_ops_summary.

Trace and output requirements:
- Return structured pipeline trace for all attempted steps.
- Include for each step:
  - status
  - concise summary (1-2 sentences)
  - key_findings (<= 5 short bullets)
- final_member_message must be actionable and specific (never generic).
- final_ops_summary must clearly describe why pipeline stopped or what the final decision is.
- Include blockers and warnings as explicit lists.

Resilience rules:
- If a sub-agent fails unexpectedly, capture error in trace and return MANUAL_REVIEW with clear ops message.
- Do not let unexpected errors cause total pipeline failure; handle gracefully with traceable output.
"""

gate_tool = AgentTool(document_gate_agent)
requirements_tool = AgentTool(document_requirements_agent)
extraction_tool = AgentTool(document_extraction_agent)
consistency_tool = AgentTool(consistency_check_agent)

claims_pipeline_agent = LlmAgent(
    model=MODEL,
    name="claims_pipeline_agent",
    description=(
        "Root orchestrator that runs document gate, extraction, consistency checks, "
        "and policy decision with strict stage control and full trace output."
    ),
    instruction=ROOT_PIPELINE_PROMPT,
    generate_content_config=GenerateContentConfig(
        temperature=0.1,
        top_p=1.0,
        top_k=1.0,
    ),
    tools=[gate_tool, requirements_tool, extraction_tool, consistency_tool, run_policy_decision],
    output_schema=PipelineTrace,
    output_key="pipeline_trace",
)

root_agent = claims_pipeline_agent
