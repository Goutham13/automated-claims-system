"""Document extraction agent for claim documents (text-driven input)."""

from __future__ import annotations

from typing import Literal

from google.adk.agents import LlmAgent
from google.genai.types import GenerateContentConfig
from pydantic import BaseModel, Field

MODEL = "gemini-3-flash-preview"

DocumentType = Literal[
    "PRESCRIPTION",
    "HOSPITAL_BILL",
    "LAB_REPORT",
    "PHARMACY_BILL",
    "DENTAL_REPORT",
    "DISCHARGE_SUMMARY",
]


class ExtractionInputDocument(BaseModel):
    file_id: str = Field(description="Unique file id.")
    file_name: str = Field(description="Uploaded file name.")
    document_type: DocumentType = Field(description="Document type from previous classification step.")
    document_text: str = Field(description="Plain text content extracted by root agent from the document.")


class MedicineItem(BaseModel):
    medicine_name: str | None = None
    strength_or_dosage: str | None = None
    frequency: str | None = None
    duration: str | None = None
    instruction: str | None = None


class OrderedTest(BaseModel):
    test_name: str | None = None
    note: str | None = None


class BillLineItem(BaseModel):
    description: str | None = None
    quantity: str | None = None
    unit_rate: float | None = None
    amount: float | None = None
    category_hint: str | None = Field(
        default=None,
        description="Optional normalized hint like CONSULTATION, DIAGNOSTIC, MEDICINE, PROCEDURE.",
    )


class LabResultItem(BaseModel):
    test_name: str | None = None
    result_value: str | None = None
    unit: str | None = None
    normal_range: str | None = None
    interpretation: str | None = None


class PharmacyItem(BaseModel):
    medicine_name: str | None = None
    batch_no: str | None = None
    expiry: str | None = None
    quantity: str | None = None
    mrp: float | None = None
    amount: float | None = None


class PrescriptionFields(BaseModel):
    doctor_name: str | None = None
    doctor_registration_number: str | None = None
    doctor_specialization: str | None = None
    hospital_or_clinic_name: str | None = None
    hospital_or_clinic_address: str | None = None
    patient_name: str | None = None
    patient_age: str | None = None
    patient_gender: str | None = None
    prescription_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD when inferable.")
    chief_complaint: str | None = None
    diagnosis_primary: str | None = None
    diagnosis_secondary: list[str] = Field(default_factory=list)
    medicines: list[MedicineItem] = Field(default_factory=list)
    tests_ordered: list[OrderedTest] = Field(default_factory=list)
    follow_up_instructions: str | None = None


class HospitalBillFields(BaseModel):
    hospital_name: str | None = None
    hospital_address: str | None = None
    gstin: str | None = None
    bill_number: str | None = None
    bill_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD when inferable.")
    patient_name: str | None = None
    patient_age: str | None = None
    patient_gender: str | None = None
    referring_doctor_name: str | None = None
    line_items: list[BillLineItem] = Field(default_factory=list)
    subtotal_amount: float | None = None
    gst_amount: float | None = None
    discount_amount: float | None = None
    total_amount: float | None = None
    payment_mode: str | None = None


class LabReportFields(BaseModel):
    lab_name: str | None = None
    lab_address: str | None = None
    nabl_accredited: bool | None = None
    lab_id: str | None = None
    sample_id: str | None = None
    patient_name: str | None = None
    patient_age: str | None = None
    patient_gender: str | None = None
    referring_doctor_name: str | None = None
    sample_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD when inferable.")
    report_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD when inferable.")
    test_results: list[LabResultItem] = Field(default_factory=list)
    remarks: str | None = None
    pathologist_name: str | None = None
    pathologist_registration_number: str | None = None


class PharmacyBillFields(BaseModel):
    pharmacy_name: str | None = None
    pharmacy_address: str | None = None
    drug_license_number: str | None = None
    bill_number: str | None = None
    bill_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD when inferable.")
    patient_name: str | None = None
    prescribing_doctor_name: str | None = None
    medicines: list[PharmacyItem] = Field(default_factory=list)
    subtotal_amount: float | None = None
    discount_amount: float | None = None
    net_amount: float | None = None
    pharmacist_name: str | None = None


class DentalReportFields(BaseModel):
    dentist_name: str | None = None
    dentist_registration_number: str | None = None
    clinic_name: str | None = None
    patient_name: str | None = None
    diagnosis: str | None = None
    procedures_recommended_or_done: list[str] = Field(default_factory=list)
    notes: str | None = None


class DischargeSummaryFields(BaseModel):
    hospital_name: str | None = None
    patient_name: str | None = None
    admission_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD when inferable.")
    discharge_date: str | None = Field(default=None, description="ISO date YYYY-MM-DD when inferable.")
    final_diagnosis: str | None = None
    treatment_summary: str | None = None
    discharge_advice: str | None = None


class DocumentExtractionResult(BaseModel):
    file_id: str
    file_name: str
    document_type: DocumentType
    extraction_confidence: float = Field(description="0.0-1.0 extraction confidence.")
    missing_critical_fields: list[str] = Field(default_factory=list)
    prescription: PrescriptionFields | None = None
    hospital_bill: HospitalBillFields | None = None
    lab_report: LabReportFields | None = None
    pharmacy_bill: PharmacyBillFields | None = None
    dental_report: DentalReportFields | None = None
    discharge_summary: DischargeSummaryFields | None = None
    extraction_notes: list[str] = Field(
        default_factory=list,
        description="Short notes for assumptions, uncertain interpretation, or missing data context.",
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description="Concise, high-signal extraction highlights for UI step progress.",
    )
    ops_message: str = Field(
        description="Concise operations message for pipeline trace."
    )


DOCUMENT_EXTRACTION_PROMPT = """
You are a medical document extraction specialist for health insurance claims.

Goal:
- Extract structured fields from a single input document using the provided `document_type` and `document_text`.
- Return strict JSON matching the schema.

Input assumptions:
- You receive text only (`document_text`) from the root agent.
- Use only the provided text; never invent values.

Extraction rules:
1) If value is not present in text, set null.
2) Normalize dates to YYYY-MM-DD when inferable; else keep null and add note.
3) Extract numeric currency fields as float numbers without currency symbols.
4) Preserve medically relevant strings exactly where possible (diagnosis, test names, procedure names).
5) Provide `missing_critical_fields` for the chosen `document_type`.

Document-specific extraction guidance (including critical fields):

PRESCRIPTION:
- Extract doctor details, registration number, specialization, clinic name/address.
- Extract patient details, date, complaint, diagnosis (primary + secondary), medicines,
  ordered tests, follow-up instructions, signature/stamp presence.
- Critical fields: patient_name, prescription_date, diagnosis_primary, doctor_name.

HOSPITAL_BILL:
- Extract provider header (name/address/GSTIN), bill number/date, patient details,
  line-items, subtotal/GST/discount/total, payment mode, receiver.
- Critical fields: patient_name, bill_date, total_amount.

LAB_REPORT:
- Extract lab details, sample/report metadata, patient details, test rows,
  pathologist details, remarks.
- Critical fields: patient_name, report_date, test_results.

PHARMACY_BILL:
- Extract pharmacy details, drug license, bill metadata, patient/doctor names,
  medicine rows, subtotal/discount/net amount.
- Critical fields: patient_name, bill_date, net_amount.

DENTAL_REPORT:
- Extract dentist/clinic details, patient name, diagnosis, procedures done/recommended.
- Critical fields: patient_name, diagnosis, procedures_recommended_or_done.

DISCHARGE_SUMMARY:
- Extract admission/discharge dates, final diagnosis, treatment summary, discharge advice.
- Critical fields: patient_name, discharge_date, final_diagnosis.

Output constraints:
- Return JSON only, no markdown.
- Populate only the typed section matching `document_type`; keep unrelated sections null.
- Always provide `ops_message` and `key_findings`.
"""


document_extraction_agent = LlmAgent(
    model=MODEL,
    name="document_extraction_agent",
    description=(
        "Extracts structured claim fields from text content for a single classified document."
    ),
    instruction=DOCUMENT_EXTRACTION_PROMPT,
    generate_content_config=GenerateContentConfig(
        temperature=0.1,
        top_p=1.0,
        top_k=1.0,
    ),
    input_schema=ExtractionInputDocument,
    output_schema=DocumentExtractionResult,
    output_key="document_extraction_result",
)
