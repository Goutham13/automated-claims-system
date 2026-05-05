# Component Contracts

For every significant component in the system: exact input schema, output schema, error behaviour, and behavioural invariants. Precise enough to reimplement any component without reading its source code.

---

## Table of Contents

1. [API: POST /auth/login](#1-api-post-authlogin)
2. [API: POST /claims](#2-api-post-claims)
3. [API: GET /claims/{claim_id}/events (SSE)](#3-api-get-claimsclaim_idevents-sse)
4. [API: GET /staff/claims](#4-api-get-staffclaims)
5. [Tool: save_extracted_document_text](#5-tool-save_extracted_document_text)
6. [Agent: Root Pipeline Orchestrator (claims_pipeline_agent)](#6-agent-root-pipeline-orchestrator)
7. [Agent: Document Gate Agent](#7-agent-document-gate-agent)
8. [Agent: Document Requirements Agent](#8-agent-document-requirements-agent)
9. [Agent: Document Extraction Agent](#9-agent-document-extraction-agent)
10. [Agent: Consistency Check Agent](#10-agent-consistency-check-agent)
11. [Function: run_policy_decision](#11-function-run_policy_decision)
12. [Policy Sub-checks (Internal)](#12-policy-sub-checks-internal)
13. [DB Layer: claims_history tools](#13-db-layer-claims_history-tools)

---

## 1. API: POST /auth/login

**File**: `api/main.py` + `api/auth.py`

### Request
```
POST /auth/login
Content-Type: application/json

{
  "username": string,   // member ID (e.g. "EMP001") or staff username
  "password": string
}
```

### Response (200 OK)
```json
{
  "token": "string",     // HMAC-signed bearer token (no expiry)
  "role":  "member" | "staff",
  "name":  "string",     // Display name
  "sub":   "string"      // Same as username
}
```

### Errors
| Status | Condition |
|---|---|
| 401 | Username not found, or password does not match |

### Token format
```
base64url(payload_json) + "." + HMAC-SHA256(base64url(payload_json), AUTH_SECRET)
```
Payload JSON: `{"sub": str, "role": str, "name": str, "iat": unix_epoch_int}`

No expiry is enforced. Token is valid until the server secret changes.

### Known accounts (default env)
- Staff: username=`staff`, password=`staff@123`
- Members: username=`EMP001`–`EMP010`, `DEP001`–`DEP002`, password=`member123`

---

## 2. API: POST /claims

**File**: `api/main.py`

### Request
```
POST /claims
Content-Type: multipart/form-data
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `member_id` | string | yes | Must exist in `policy_terms.json` members list |
| `policy_id` | string | yes | Stored as-is; not validated beyond presence |
| `claim_category` | string | yes | `CONSULTATION \| DIAGNOSTIC \| PHARMACY \| DENTAL \| VISION \| ALTERNATIVE_MEDICINE` |
| `treatment_date` | string | yes | `YYYY-MM-DD` format |
| `claimed_amount` | float | yes | Positive number |
| `relationship_claim_type` | string | yes | `SELF \| DEPENDENT` |
| `patient_member_id` | string | no | Required if `relationship_claim_type=DEPENDENT` |
| `has_pre_authorization` | bool | no | Default `false` |
| `documents` | file[] | yes | At least 1 file; PDF/JPEG/PNG; max 10 MB each |

### Response (200 OK)
```json
{
  "claim_id":   "uuid-string",
  "user_id":    "uuid-string",
  "session_id": "uuid-string"
}
```

### Errors
| Status | Condition |
|---|---|
| 400 | No documents uploaded |
| 413 | Any file exceeds 10 MB |
| 415 | File MIME type is not `application/pdf`, `image/jpeg`, `image/jpg`, or `image/png` |
| 422 | `member_id` not found in `policy_terms.json` |

### Side effects
1. Inserts row into `claims` table
2. Inserts one row per document into `claim_documents` table (raw bytes stored as BYTEA)
3. Inserts row into `claims_history` table (for YTD utilization tracking), with `is_approved=FALSE`
4. File IDs are assigned sequentially: `F001`, `F002`, `F003`, ... based on upload order

---

## 3. API: GET /claims/{claim_id}/events (SSE)

**File**: `api/main.py`

### Request
```
GET /claims/{claim_id}/events
Accept: text/event-stream
```

No authentication required on this endpoint.

### Response
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

data: {event_json}\n\n
data: {event_json}\n\n
...
```

### Event types

**ADK agent events** (normal operation):
```json
{
  "author": "claims_pipeline_agent" | "document_gate_agent" | ...,
  "content": {
    "role": "model",
    "parts": [{"text": "..."} | {"function_call": {...}} | {"function_response": {...}}]
  },
  "partial": true | false,
  "is_final_response": true | false,
  "actions": {
    "state_delta": {
      "final_status": "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW" | "STOPPED_AT_GATE" | "STOPPED_AT_CONSISTENCY" | "PENDING_MEMBER_ACTION",
      "final_member_message": "string",
      "final_ops_summary": "string",
      "blockers": ["string"],
      "warnings": ["string"],
      "policy_decision": { ... } | null,
      "DOCUMENT_CLASSIFICATION": {"status": "...", "summary": "...", "key_findings": [...]},
      "DOCUMENT_REQUIREMENTS":   {"status": "...", "summary": "...", "key_findings": [...]},
      "DOCUMENT_EXTRACTION":     {"status": "...", "summary": "...", "key_findings": [...]},
      "CONSISTENCY_CHECK":       {"status": "...", "summary": "...", "key_findings": [...]},
      "POLICY_DECISION":         {"status": "...", "summary": "...", "key_findings": [...]}
    }
  },
  "claim_id": "string",
  "user_id":  "string",
  "session_id": "string",
  "created_at": "ISO-8601 timestamp"
}
```

`state_delta` is only present on events that carry it. Step keys (`DOCUMENT_CLASSIFICATION`, etc.) are only present after that stage runs.

**Partial tool-only events are filtered**: Events where `partial=true` and all parts are function_call/function_response are silently dropped before forwarding to the client.

**Completion event** (always emitted after the agent finishes):
```json
{
  "type": "pipeline_completion",
  "author": "claims_pipeline_agent",
  "pipeline_complete": true,
  "claim_id": "string",
  "user_id": "string",
  "session_id": "string",
  "created_at": "ISO-8601 timestamp"
}
```

**Error event — claim not found (4040)**:
```json
{
  "type": "error",
  "message": "Claim not found.",
  "code": 4040,
  "claim_id": "string",
  "created_at": "ISO-8601 timestamp"
}
```

**Error event — processing failure (5001)**:
```json
{
  "type": "error",
  "message": "An error occurred while processing the claim. Please try again.",
  "code": 5001,
  "claim_id": "string",
  "user_id": "string",
  "session_id": "string",
  "created_at": "ISO-8601 timestamp"
}
```

### Side effects on completion
1. Reads `pipeline_trace` from in-memory session state
2. Writes `final_status` and `pipeline_trace` (JSONB) to `claims` table
3. If `final_status` is `APPROVED` or `PARTIAL`, sets `is_approved=TRUE` in `claims_history`

### Errors
| Condition | Behaviour |
|---|---|
| claim_id not in DB | Emits error event (code 4040), stream ends |
| Agent exception during processing | Emits error event (code 5001), stream ends |
| DB write-back failure after agent completes | Logged as warning; completion event still emitted |

---

## 4. API: GET /staff/claims

**File**: `api/main.py`

### Request
```
GET /staff/claims
Authorization: Bearer {token}
```

### Response (200 OK)
```json
{
  "claims": [
    {
      "claim_id": "string",
      "user_id": "string",
      "member_id": "string",
      "policy_id": "string",
      "claim_category": "string",
      "treatment_date": "YYYY-MM-DD",
      "claimed_amount": number,
      "relationship_claim_type": "string",
      "patient_member_id": "string" | null,
      "has_pre_authorization": boolean,
      "final_status": "string" | null,
      "pipeline_trace": { ... } | null,
      "created_at": "ISO-8601 timestamp",
      "documents": [
        {
          "file_id": "string",
          "file_name": "string",
          "mime_type": "string"
        }
      ]
    }
  ]
}
```

Document entries do **not** include `file_data` (bytes are not returned).

### Errors
| Status | Condition |
|---|---|
| 401 | Missing or invalid Authorization header |
| 403 | Token is valid but `role != "staff"` |

---

## 5. Tool: save_extracted_document_text

**File**: `api/tools/extracted_text_store.py`
**Called by**: Root pipeline agent (Stage 1, after OCR)

### Signature
```python
async def save_extracted_document_text(
    file_id: str,        # e.g. "F001"
    file_name: str,      # original filename
    document_text: str,  # extracted plain text (may be partial/empty)
    tool_context: ToolContext,  # ADK-injected; not passed by the LLM
) -> dict
```

### Return value (always succeeds)
```json
{
  "status": "saved",
  "file_id": "F001",
  "file_name": "prescription.pdf",
  "artifact_filename": "extracted_text__F001-prescription_pdf.txt",
  "artifact_version": 0,
  "char_count": 1234
}
```

### Side effects
1. Saves text as a session-scoped ADK artifact (`text/plain; charset=utf-8`)
2. Updates `session.state["doc:extracted_text_index"]` with metadata entry for this file
3. Artifact filename format: `extracted_text__{file_id}-{sanitized_file_name}.txt`
   - Sanitization: strips leading/trailing whitespace; replaces non-`[a-zA-Z0-9._-]` chars with `_`; truncates to 120 chars

### Errors
No exceptions are raised. If `document_text` is empty, saves an empty artifact with `char_count=0`. ADK artifact save failures propagate as-is (not caught here).

---

## 6. Agent: Root Pipeline Orchestrator

**File**: `api/agents/agent.py`
**Model**: `gemini-2.5-pro`
**Temperature**: 0.1

### Input
Provided as a multi-part `Content` object by the SSE endpoint:
- `Part.from_text(...)`: JSON-encoded claim metadata including:
```json
{
  "claim_id": "string",
  "member_id": "string",
  "policy_id": "string",
  "claim_category": "CONSULTATION | DIAGNOSTIC | PHARMACY | DENTAL | VISION | ALTERNATIVE_MEDICINE",
  "treatment_date": "YYYY-MM-DD",
  "claimed_amount": number,
  "relationship_claim_type": "SELF | DEPENDENT",
  "patient_member_id": "string | null",
  "has_pre_authorization": boolean,
  "documents": [{"file_id": "F001", "file_name": "...", "mime_type": "..."}]
}
```
- `Part.from_bytes(...)` per document: raw file bytes with MIME type

### Output schema (`PipelineTrace`)
Stored under session state key `pipeline_trace`:

```python
class PipelineStepResult:
    step_name:    Literal["DOCUMENT_CLASSIFICATION", "DOCUMENT_REQUIREMENTS",
                          "DOCUMENT_EXTRACTION", "CONSISTENCY_CHECK", "POLICY_DECISION"]
    status:       Literal["COMPLETED", "SKIPPED", "BLOCKED", "PENDING_REUPLOAD",
                          "MANUAL_REVIEW_RECOMMENDED"]
    summary:      str          # 1–2 sentences
    key_findings: list[str]    # ≤5 bullets

class PipelineTrace:
    steps:                list[PipelineStepResult]
    final_status:         Literal["APPROVED", "PARTIAL", "REJECTED", "MANUAL_REVIEW",
                                  "STOPPED_AT_GATE", "STOPPED_AT_CONSISTENCY",
                                  "PENDING_MEMBER_ACTION", "MANUAL_REVIEW_RECOMMENDED"]
    final_member_message: str   # specific and actionable; never generic
    final_ops_summary:    str
    blockers:             list[str]
    warnings:             list[str]
    policy_decision:      PolicyDecision | None
```

### Execution order (strictly enforced)
```
Stage 1: save_extracted_document_text for every file
Stage 2: document_gate_agent for every file (one call per file)
         → if ANY gate_outcome == PENDING_REUPLOAD: STOP, final_status = PENDING_MEMBER_ACTION
Stage 3: document_requirements_agent
         → if outcome == BLOCKED: STOP, final_status = STOPPED_AT_GATE
         → if outcome == PENDING_REUPLOAD: STOP, final_status = PENDING_MEMBER_ACTION
Stage 4: document_extraction_agent for every gate-passed file
Stage 5: consistency_check_agent
         → if outcome == BLOCKED: STOP, final_status = STOPPED_AT_CONSISTENCY
Stage 6: run_policy_decision
         → final_status = decision field from result
```

### Tools available to the agent
- `save_extracted_document_text` (Stage 1)
- `document_gate_agent` wrapped as `AgentTool` (Stage 2)
- `document_requirements_agent` wrapped as `AgentTool` (Stage 3)
- `document_extraction_agent` wrapped as `AgentTool` (Stage 4)
- `consistency_check_agent` wrapped as `AgentTool` (Stage 5)
- `run_policy_decision` Python function (Stage 6)

### Error behaviour
- Any unexpected sub-agent exception → mark that step `MANUAL_REVIEW_RECOMMENDED` in trace; set `final_status = MANUAL_REVIEW`
- Agent never raises; always produces a `PipelineTrace` JSON output

---

## 7. Agent: Document Gate Agent

**File**: `api/agents/document_gate_agent/agent.py`
**Model**: `gemini-2.5-flash`
**Temperature**: 0.1

### Input schema (`UploadedDocumentInput`)
```python
{
  "file_id":       str,  # e.g. "F001"
  "file_name":     str,  # e.g. "prescription.pdf"
  "document_text": str   # plain text extracted from the document (may be partial/empty)
}
```

### Output schema (`DocumentClassificationResult`)
```python
{
  "file_id":                   str,
  "file_name":                 str,
  "predicted_type":            "PRESCRIPTION" | "HOSPITAL_BILL" | "LAB_REPORT" |
                               "PHARMACY_BILL" | "DENTAL_REPORT" | "DISCHARGE_SUMMARY" | "UNKNOWN",
  "confidence_score":          float,   # 0.0–1.0
  "confidence_band":           "HIGH" | "MEDIUM" | "LOW",
  "extracted_signals":         list[str],  # evidence snippets from text that support classification
  "missing_required_signals":  list[str],  # signals that are mandatory but absent
  "gate_outcome":              "PASS" | "PENDING_REUPLOAD",
  "key_findings":              list[str],
  "ops_message":               str
}
```

### Classification rules

| Document Type | Required Signals (need ≥2) |
|---|---|
| PRESCRIPTION | Doctor identifier, diagnosis/complaint, medicine entry |
| HOSPITAL_BILL | Bill/invoice identifier, patient name, monetary amount or line items |
| LAB_REPORT | Test name with result, lab identifier, report/sample date |
| PHARMACY_BILL | Pharmacy identifier, at least one medicine entry, monetary amount |
| DENTAL_REPORT | Dental procedure/diagnosis term, dentist or clinic identifier |
| DISCHARGE_SUMMARY | Admission/discharge dates, final diagnosis, hospital identifier |

### Confidence band thresholds
- HIGH (≥0.80): All required signals present and unambiguous
- MEDIUM (0.50–0.79): Most required signals present; minor gaps
- LOW (<0.50): Significant signals missing; best guess only

### Gate outcome rules (deterministic)
`PENDING_REUPLOAD` if ANY of:
- `confidence_band == "LOW"` (too few signals)
- Text is mostly empty, garbled, or filled with `[UNREADABLE]` placeholders
- `predicted_type == "UNKNOWN"`

`PASS` if `confidence_band` is `HIGH` or `MEDIUM` AND required signals are present.

**Critical**: A type guess from 1–2 words is NOT sufficient for PASS. Sufficient signals are required.

### Errors
No exceptions. The agent always returns a valid `DocumentClassificationResult`. If text is completely empty, `predicted_type = "UNKNOWN"`, `gate_outcome = "PENDING_REUPLOAD"`, `confidence_score = 0.0`.

---

## 8. Agent: Document Requirements Agent

**File**: `api/agents/document_requirements_agent/agent.py`
**Model**: `gemini-3-flash-preview`
**Temperature**: 0.1

### Input schema (`DocumentRequirementsInput`)
```python
{
  "claim_category":  "CONSULTATION" | "DIAGNOSTIC" | "PHARMACY" | "DENTAL" |
                     "VISION" | "ALTERNATIVE_MEDICINE",
  "predicted_types": list[str]  # per-file predicted types; may contain duplicates and "UNKNOWN"
}
```

**Important**: `predicted_types` is a flat list of strings (not objects). Example: `["PRESCRIPTION", "HOSPITAL_BILL"]`.

### Output schema (`DocumentRequirementsResult`)
```python
{
  "outcome":                "PASS" | "BLOCKED" | "PENDING_REUPLOAD",
  "claim_category":         str,
  "required_types":         list[str],   # canonical required list for this category
  "missing_required_types": list[str],   # types that are required but not in predicted_types
  "ops_message":            str,
  "key_findings":           list[str]
}
```

### Requirements matrix

| Category | Required | Optional |
|---|---|---|
| CONSULTATION | PRESCRIPTION, HOSPITAL_BILL | LAB_REPORT |
| DIAGNOSTIC | PRESCRIPTION, LAB_REPORT, HOSPITAL_BILL | DISCHARGE_SUMMARY |
| PHARMACY | PRESCRIPTION, PHARMACY_BILL | — |
| DENTAL | HOSPITAL_BILL | PRESCRIPTION, DENTAL_REPORT |
| VISION | PRESCRIPTION, HOSPITAL_BILL | — |
| ALTERNATIVE_MEDICINE | PRESCRIPTION, HOSPITAL_BILL | — |

### Outcome rules
- `PASS`: all required types satisfied (presence, not uniqueness — duplicates are fine)
- `PENDING_REUPLOAD`: any required type is missing (preferred outcome; includes specific guidance)
- `BLOCKED`: upload set is clearly wrong and cannot satisfy requirements (e.g. 3 prescriptions, no bill for CONSULTATION); use sparingly

### Error behaviour
Always returns a valid result. If `predicted_types` is empty, all required types are missing → `PENDING_REUPLOAD`.

---

## 9. Agent: Document Extraction Agent

**File**: `api/agents/document_extraction_agent/agent.py`
**Model**: `gemini-3-flash-preview`
**Temperature**: 0.1

### Input schema (`ExtractionInputDocument`)
```python
{
  "file_id":       str,           # e.g. "F001"
  "file_name":     str,
  "document_type": "PRESCRIPTION" | "HOSPITAL_BILL" | "LAB_REPORT" |
                   "PHARMACY_BILL" | "DENTAL_REPORT" | "DISCHARGE_SUMMARY",
  "document_text": str            # plain text only; NO raw bytes
}
```

### Output schema (`DocumentExtractionResult`)
```python
{
  "file_id":                str,
  "file_name":              str,
  "document_type":          str,
  "extraction_confidence":  float,       # 0.0–1.0
  "missing_critical_fields": list[str],  # named fields that are required but absent
  "prescription":           PrescriptionFields | None,
  "hospital_bill":          HospitalBillFields | None,
  "lab_report":             LabReportFields | None,
  "pharmacy_bill":          PharmacyBillFields | None,
  "dental_report":          DentalReportFields | None,
  "discharge_summary":      DischargeSummaryFields | None,
  "extraction_notes":       list[str],
  "key_findings":           list[str],
  "ops_message":            str
}
```

Exactly one typed section is populated (matching `document_type`). All others are `null`.

### Type-specific field schemas

**PrescriptionFields**:
```python
doctor_name:                str | None
doctor_registration_number: str | None   # format: KA/12345/2020
doctor_specialization:      str | None
hospital_or_clinic_name:    str | None
hospital_or_clinic_address: str | None
patient_name:               str | None
patient_age:                str | None
patient_gender:             str | None
prescription_date:          str | None   # YYYY-MM-DD
chief_complaint:            str | None
diagnosis_primary:          str | None
diagnosis_secondary:        list[str]
medicines:                  list[MedicineItem]
tests_ordered:              list[OrderedTest]
follow_up_instructions:     str | None
```

**MedicineItem**: `medicine_name`, `strength_or_dosage`, `frequency`, `duration`, `instruction` — all `str | None`

**OrderedTest**: `test_name`, `note` — all `str | None`

**HospitalBillFields**:
```python
hospital_name:         str | None
hospital_address:      str | None
gstin:                 str | None
bill_number:           str | None
bill_date:             str | None   # YYYY-MM-DD
patient_name:          str | None
patient_age:           str | None
patient_gender:        str | None
referring_doctor_name: str | None
line_items:            list[BillLineItem]
subtotal_amount:       float | None
gst_amount:            float | None
discount_amount:       float | None
total_amount:          float | None
payment_mode:          str | None
```

**BillLineItem**: `description`, `quantity` (str), `unit_rate` (float), `amount` (float), `category_hint` (str: `CONSULTATION | DIAGNOSTIC | MEDICINE | PROCEDURE`) — all nullable

**LabReportFields**:
```python
lab_name:                         str | None
lab_address:                      str | None
nabl_accredited:                  bool | None
lab_id:                           str | None
sample_id:                        str | None
patient_name:                     str | None
patient_age:                      str | None
patient_gender:                   str | None
referring_doctor_name:            str | None
sample_date:                      str | None   # YYYY-MM-DD
report_date:                      str | None   # YYYY-MM-DD
test_results:                     list[LabResultItem]
remarks:                          str | None
pathologist_name:                 str | None
pathologist_registration_number:  str | None
```

**LabResultItem**: `test_name`, `result_value`, `unit`, `normal_range`, `interpretation` — all `str | None`

**PharmacyBillFields**:
```python
pharmacy_name:          str | None
pharmacy_address:       str | None
drug_license_number:    str | None
bill_number:            str | None
bill_date:              str | None   # YYYY-MM-DD
patient_name:           str | None
prescribing_doctor_name: str | None
medicines:              list[PharmacyItem]
subtotal_amount:        float | None
discount_amount:        float | None
net_amount:             float | None
pharmacist_name:        str | None
```

**PharmacyItem**: `medicine_name`, `batch_no`, `expiry`, `quantity` (str), `mrp` (float), `amount` (float) — all nullable

**DentalReportFields**:
```python
dentist_name:                     str | None
dentist_registration_number:      str | None
clinic_name:                      str | None
patient_name:                     str | None
diagnosis:                        str | None
procedures_recommended_or_done:   list[str]
notes:                            str | None
```

**DischargeSummaryFields**:
```python
hospital_name:      str | None
patient_name:       str | None
admission_date:     str | None   # YYYY-MM-DD
discharge_date:     str | None   # YYYY-MM-DD
final_diagnosis:    str | None
treatment_summary:  str | None
discharge_advice:   str | None
```

### Critical fields by type (populate `missing_critical_fields` if absent)
| Type | Critical Fields |
|---|---|
| PRESCRIPTION | `patient_name`, `prescription_date`, `diagnosis_primary`, `doctor_name` |
| HOSPITAL_BILL | `patient_name`, `bill_date`, `total_amount` |
| LAB_REPORT | `patient_name`, `report_date`, `test_results` |
| PHARMACY_BILL | `patient_name`, `bill_date`, `net_amount` |
| DENTAL_REPORT | `patient_name`, `diagnosis`, `procedures_recommended_or_done` |
| DISCHARGE_SUMMARY | `patient_name`, `discharge_date`, `final_diagnosis` |

### Invariants
- **Non-hallucinatory**: absent fields are `null`, never guessed
- All dates normalized to `YYYY-MM-DD` if inferable; `null` otherwise
- All monetary amounts are `float` without currency symbols
- Medically relevant strings (diagnosis names, test names) preserved verbatim
- Only the section matching `document_type` is populated; all others are `null`

### Errors
Always returns a valid `DocumentExtractionResult`. If text is completely unreadable, all fields are `null` and `extraction_confidence` is low.

---

## 10. Agent: Consistency Check Agent

**File**: `api/agents/consistency_check_agent/agent.py`
**Model**: `gemini-3-flash-preview`
**Temperature**: 0.1

### Input schema (`ConsistencyCheckInput`)
```python
{
  "claimed_amount":     float | None,
  "treatment_date":     str | None,   # YYYY-MM-DD
  "extracted_documents": str           # JSON-serialised list of DocumentConsistencySnapshot
}
```

**DocumentConsistencySnapshot** (the object structure inside the JSON string):
```python
{
  "file_id":       str,
  "file_name":     str,
  "document_type": str,          # e.g. "PRESCRIPTION"
  "patient_name":  str | None,
  "primary_date":  str | None,   # YYYY-MM-DD — whichever date field is populated
  "amount":        float | None, # hospital_bill.total_amount or pharmacy_bill.net_amount
  "diagnosis":     str | None,
  "provider_name": str | None,   # hospital, clinic, lab, or pharmacy name
  "doctor_name":   str | None
}
```

**How root agent builds snapshots from `DocumentExtractionResult`**:
| Snapshot field | Source (first non-null of) |
|---|---|
| `patient_name` | prescription.patient_name, hospital_bill.patient_name, lab_report.patient_name, pharmacy_bill.patient_name, dental_report.patient_name, discharge_summary.patient_name |
| `primary_date` | prescription.prescription_date, hospital_bill.bill_date, lab_report.report_date, pharmacy_bill.bill_date, discharge_summary.discharge_date |
| `amount` | hospital_bill.total_amount, pharmacy_bill.net_amount |
| `diagnosis` | prescription.diagnosis_primary, dental_report.diagnosis, discharge_summary.final_diagnosis |
| `provider_name` | prescription.hospital_or_clinic_name, hospital_bill.hospital_name, lab_report.lab_name, pharmacy_bill.pharmacy_name |
| `doctor_name` | prescription.doctor_name, hospital_bill.referring_doctor_name, lab_report.referring_doctor_name |

### Output schema (`ConsistencyCheckResult`)
```python
{
  "outcome":          "PASS" | "BLOCKED" | "MANUAL_REVIEW_RECOMMENDED",
  "confidence_score": float,        # 0.0–1.0
  "ops_message":      str,          # specific — names conflicting values
  "key_findings":     list[str],
  "issues":           list[ConsistencyIssue]
}
```

**ConsistencyIssue**:
```python
{
  "issue_code":          str,        # e.g. "PATIENT_NAME_MISMATCH", "DATE_MISMATCH", "AMOUNT_MISMATCH"
  "severity":            "INFO" | "WARNING" | "BLOCKER",
  "description":         str,
  "affected_file_names": list[str],
  "evidence":            list[str]   # concrete value pairs, e.g. ["Rajesh Kumar (F001)", "Arjun Mehta (F002)"]
}
```

### Checks performed (in order)

| Check | Issue Code | Severity | Rule |
|---|---|---|---|
| Patient Identity | `PATIENT_NAME_MISMATCH` | BLOCKER (clear mismatch) / INFO (formatting) | Compare `patient_name` across all non-null snapshots |
| Date Consistency | `DATE_MISMATCH` | BLOCKER (primary docs, >3 days) / WARNING (supporting docs) | Compare each `primary_date` against `treatment_date` |
| Amount Consistency | `AMOUNT_MISMATCH` | WARNING | Sum of non-null `amount` values vs `claimed_amount`; flag if >10% over |
| Provider Cross-reference | `PROVIDER_MISMATCH` | INFO / WARNING | Compare `provider_name` and `doctor_name` across docs |
| Diagnosis Alignment | `DIAGNOSIS_MISMATCH` | WARNING | Check `diagnosis` values are medically plausible together |

Primary documents for date check: `PRESCRIPTION`, `HOSPITAL_BILL`. Supporting: everything else.

### Outcome rules
- `BLOCKED`: any issue with `severity == "BLOCKER"`
- `MANUAL_REVIEW_RECOMMENDED`: no BLOCKER but ≥1 WARNING
- `PASS`: no issues, or INFO-level issues only

### Invariants
- Only uses pre-extracted snapshot fields; never re-derives values from raw text
- `ops_message` always names specific conflicting values (never generic)

### Errors
Always returns a valid `ConsistencyCheckResult`. If `extracted_documents` is empty JSON `"[]"`, returns `PASS` with no issues.

---

## 11. Function: run_policy_decision

**File**: `api/agents/policy_decision_agent/agent.py`
**Type**: Pure Python function, no LLM. Same inputs always produce same output.

### Signature
```python
def run_policy_decision(
    member_id:                str,
    policy_id:                str,
    claim_category:           str,
    treatment_date:           str,   # YYYY-MM-DD
    claimed_amount:           float,
    has_pre_authorization:    bool,
    relationship_claim_type:  str,   # "SELF" | "DEPENDENT"
    patient_member_id:        str | None,
    extracted_documents_json: str,   # JSON list of DocumentExtractionResult dicts
    claims_history_json:      str = "[]",  # JSON list of {claim_id, date, amount}
) -> dict
```

### Return value (`PolicyDecision` as dict)
```python
{
  "decision":         "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW",
  "approved_amount":  float,
  "copay_amount":     float,
  "reason":           str,    # human-readable explanation of the decision
  "confidence_score": float,  # 1.0 - 0.15 per INCONCLUSIVE check; minimum 0.3
  "rule_findings":    list[RuleFinding]
}
```

**RuleFinding**:
```python
{
  "check":  str,                                          # e.g. "MEMBER_ELIGIBILITY"
  "result": "PASS" | "FAIL" | "INCONCLUSIVE" | "MANUAL_REVIEW",
  "detail": str,
  "data":   dict   # check-specific fields (see sub-checks below)
}
```

### 7 rule checks (run in this order)
1. `DEPENDENT_COVERAGE`
2. `MEMBER_ELIGIBILITY`
3. `WAITING_PERIODS`
4. `EXCLUSIONS`
5. `PRE_AUTHORIZATION`
6. `COVERAGE_LIMITS`
7. `FRAUD_SIGNALS`

All 7 checks run regardless of intermediate failures (for trace completeness). Amount logic is skipped if already REJECTED.

### Decision priority cascade
```
APPROVED (1) < PARTIAL (2) < MANUAL_REVIEW (3) < REJECTED (4)
```
The highest-priority (numerically largest) result wins. Once REJECTED, cannot be downgraded.

### Amount calculation (COVERAGE_LIMITS → PASS path)
```python
base             = covered_bill_amount or bill_total_amount or claimed_amount
effective_base   = base * (1 - network_discount_pct/100)  # if in-network hospital
                   OR min(base, sub_limit)                 # if non-network
eligible         = min(effective_base, remaining_annual_limit)
copay            = eligible * (copay_pct / 100)
approved_amount  = eligible - copay
```
If `decision == "REJECTED"`, both `approved_amount` and `copay_amount` are set to `0.0`.

### Confidence score
```python
inconclusive_count = count of findings with result == "INCONCLUSIVE"
confidence_score   = max(0.3, 1.0 - 0.15 * inconclusive_count)
# If confidence_score <= 0.45 and decision is not REJECTED: upgrade to MANUAL_REVIEW
```

### Data sources
- `policy_terms.json` — loaded once at module import; contains members, coverage rules, exclusions, waiting periods, fraud thresholds
- `claims_history` DB table — queried via `tools/claims_history.py` (psycopg2, sync, ThreadedConnectionPool of 1–5 connections)

### Errors
- `json.JSONDecodeError` on `extracted_documents_json`: treats as empty list (no extraction data)
- `json.JSONDecodeError` on `claims_history_json`: treats as empty list
- DB connection failure in coverage/fraud checks: psycopg2 exceptions propagate to caller; root agent catches and returns `MANUAL_REVIEW`
- Missing member in policy_terms.json: `MEMBER_ELIGIBILITY` returns `FAIL` with detail message

---

## 12. Policy Sub-checks (Internal)

These are called by `run_policy_decision`. They can be reimplemented independently.

### check_dependent_coverage
```python
def check_dependent_coverage(
    member_id: str,
    patient_member_id: str | None,
    relationship_claim_type: str,
) -> dict
```

**Returns**: `{"check": "DEPENDENT_COVERAGE", "result": "PASS"|"FAIL", "detail": str, "patient_name": str|None, "relationship": str|None, "is_covered_relationship": bool}`

**Logic**:
- If `relationship_claim_type != "DEPENDENT"`: PASS (self-claim)
- If `patient_member_id` not in policy roster: FAIL
- If `patient.primary_member_id != member_id`: FAIL (not registered under this member)
- If `patient.relationship` not in `family_floater.covered_relationships`: FAIL
- Otherwise: PASS

Note: `"CHILD"` relationship is normalized to `"CHILDREN"` for comparison.

---

### check_member_eligibility
```python
def check_member_eligibility(member_id: str, treatment_date: str) -> dict
```

**Returns**: `{"check": "MEMBER_ELIGIBILITY", "result": ..., "detail": str, "member_name": str|None, "join_date": str|None, "days_since_join": int|None}`

**Logic**:
- Member not found → FAIL
- `join_date` missing → INCONCLUSIVE
- Date parse error → INCONCLUSIVE
- `days_since_join < initial_waiting_period_days (default: 30)` → FAIL with eligible-from date
- Otherwise → PASS

---

### check_waiting_periods
```python
def check_waiting_periods(member_id: str, treatment_date: str, diagnosis: str) -> dict
```

**Returns**: `{"check": "WAITING_PERIOD", "result": ..., "detail": str, "matched_condition": str|None, "required_days": int|None, "days_since_join": int|None, "eligible_from": str|None, "pre_existing_flag": bool}`

**Logic**:
1. If no diagnosis: check if `days_since_join < pre_existing_conditions_days` → INCONCLUSIVE; else PASS
2. Match diagnosis against `specific_conditions` map using whole-word, negation-aware regex
   - Negation prefixes: `"no "`, `"not "`, `"denies "`, `"without "`, `"rule out"`, `"r/o "`, `"history of"`, `"family history"`, `"h/o"`, `"risk of"`, etc.
3. If matched and `days < required_days` → FAIL
4. If matched and `days >= required_days` → PASS
5. No specific match: if `days < pre_existing_conditions_days` → INCONCLUSIVE (possible pre-existing)
6. Otherwise → PASS

Specific condition waiting periods are read from `policy_terms.json` → `waiting_periods.specific_conditions`.

---

### check_exclusions
```python
def check_exclusions(
    claim_category: str,
    diagnosis: str,
    procedures: str,
    line_items_json: str,   # JSON list of {"description": str, "amount": float}
) -> dict
```

**Returns**: `{"check": "EXCLUSIONS", "result": "PASS"|"FAIL", "detail": str, "excluded_items": list, "covered_amount": float|None, "full_exclusion": bool}`

**Logic**:
- Builds exclusion list from: `exclusions.conditions` + category-specific exclusions (dental_exclusions, vision_exclusions, excluded_procedures, excluded_items)
- Matches using longest word (>4 chars) from each exclusion phrase, negation-aware
- If line items provided:
  - Each line item matched → added to `excluded_items`
  - `covered_amount` = sum of non-excluded item amounts
  - If any excluded → FAIL (partial, not full)
- If no line items and diagnosis matches exclusion → FAIL (`full_exclusion=True`) → maps to REJECTED
- If partial exclusion → maps to PARTIAL decision

---

### check_pre_authorization
```python
def check_pre_authorization(
    claim_category: str,
    tests_ordered_json: str,   # JSON list of test name strings
    claimed_amount: float,
    has_pre_authorization: bool,
) -> dict
```

**Returns**: `{"check": "PRE_AUTHORIZATION", "result": "PASS"|"FAIL", "detail": str, "pre_auth_required": bool, "triggered_by": list[str]}`

**Triggers pre-auth requirement if ANY of**:
- Category has `requires_pre_auth: true`
- `claimed_amount > pre_auth_threshold`
- Any ordered test matches `high_value_tests_requiring_pre_auth` (case-insensitive substring match)

If triggered and `has_pre_authorization=True` → PASS. If triggered and `False` → FAIL.

---

### check_coverage_limits
```python
def check_coverage_limits(
    member_id: str,
    claim_category: str,
    claimed_amount: float,
    bill_total_amount: float | None,
    hospital_name: str | None,
    covered_bill_amount: float | None,  # from EXCLUSIONS result (partial)
    patient_member_id: str | None = None,
) -> dict
```

**Returns**: `{"check": "COVERAGE_LIMITS", "result": "PASS"|"FAIL", "detail": str, "base_amount": float, "effective_base": float, "in_network": bool, "network_discount_percent": float, "copay_percent": float, "eligible_amount": float, "approved_amount": float, "copay_amount": float, "ytd_amount": float, "family_ytd_amount": float, "remaining_annual": float, "remaining_family": float}`

**Failure conditions**:
1. `claimed_amount > max(sub_limit, per_claim_limit)` → FAIL
2. `remaining_annual <= 0` → FAIL (annual or family limit exhausted)

**Network hospital detection**: brand-word matching against `network_hospitals` list (ignores generic words like "hospital", "healthcare", "clinic", etc.)

**DB reads**: `get_ytd_claims_amount(member_id)`, `get_family_ytd_claims_amount(family_ids)` from `claims_history`

---

### check_fraud_signals
```python
def check_fraud_signals(
    member_id: str,
    treatment_date: str,
    claimed_amount: float,
    claims_history: list[dict] | None = None,
) -> dict
```

**Returns**: `{"check": "FRAUD_SIGNALS", "result": "PASS"|"MANUAL_REVIEW", "detail": str, "signals": list[str], "same_day_count": int, "monthly_count": int|None}`

**Fraud signals (from `policy_terms.json` → `fraud_thresholds`)**:
- Same-day claims > `same_day_claims_limit` (default: 2)
- Monthly claims > `monthly_claims_limit` (default: 6)
- `claimed_amount > auto_manual_review_above` (default: 25,000)

If `claims_history` list is provided (from intake), uses it for same-day count. Otherwise queries DB.

---

## 13. DB Layer: claims_history tools

**File**: `api/tools/claims_history.py`
**Client**: psycopg2 (synchronous), `ThreadedConnectionPool(minconn=1, maxconn=5)`

These are called synchronously from inside `run_policy_decision`.

### get_ytd_claims_amount(member_id: str) → float
Returns sum of `claimed_amount` for approved claims for this member in the current calendar year.
```sql
SELECT COALESCE(SUM(claimed_amount), 0)
FROM claims_history
WHERE member_id=%s AND is_approved=TRUE AND EXTRACT(YEAR FROM treatment_date)=%s
```

### get_same_day_claims_count(member_id: str, treatment_date: str) → int
```sql
SELECT COUNT(*) FROM claims_history WHERE member_id=%s AND treatment_date=%s::date
```

### get_monthly_claims_count(member_id: str, year: int, month: int) → int
```sql
SELECT COUNT(*) FROM claims_history
WHERE member_id=%s AND EXTRACT(YEAR FROM treatment_date)=%s AND EXTRACT(MONTH FROM treatment_date)=%s
```

### get_family_ytd_claims_amount(member_ids: list[str]) → float
Returns sum of YTD approved claims across all family member IDs.

### register_claim(claim_id, member_id, claimed_amount, treatment_date) → None
Inserts into `claims_history` with `is_approved=FALSE`. Uses `ON CONFLICT DO NOTHING`.

### mark_claim_approved(claim_id: str) → None
Sets `is_approved=TRUE` for the given claim.

### Error behaviour
All functions return `0.0` or `0` on DB failure (psycopg2 exceptions propagate to caller). Connection pool is lazily initialized on first call.

---

## Cross-cutting Invariants

1. **No hallucination**: all LLM agents operate at `temperature=0.1`, `top_p=1.0`, `top_k=1.0`. Extraction agents are explicitly instructed to emit `null` rather than infer missing values.

2. **Output always matches schema**: every agent uses `output_schema=` in `LlmAgent`. The ADK framework validates and coerces the output before returning it to the caller.

3. **Fail-safe policy decisions**: `run_policy_decision` catches JSON parse errors and treats them as empty input rather than raising. This means a corrupt extraction result degrades gracefully to missing-data handling rather than crashing.

4. **Structured trace at every stage**: every component emits `key_findings` (≤5 bullets) and `ops_message`. This ensures the full pipeline can be reconstructed from the trace alone.

5. **Pipeline stops at first hard failure**: any `PENDING_REUPLOAD` or `BLOCKED` outcome stops the pipeline immediately. Downstream agents are not called, preventing wasted LLM calls on bad data.
