# Architecture Documentation: Health Insurance Claims Processing System

## What This System Does

This is an AI-driven health insurance claims processing pipeline. An employee submits a claim with medical documents (bills, prescriptions, lab reports). The system automatically validates the documents, extracts structured data from them, cross-checks for consistency, and applies deterministic policy rules to decide the outcome — approved, partial, rejected, or flagged for manual review. Every decision is fully traceable.

The core problem it solves: manual claim review is slow, inconsistent, and doesn't scale. This system automates end-to-end adjudication while maintaining explainability for the operations team.

---

## System Architecture: 6-Stage Pipeline

The system is a strict, sequentially-ordered multi-agent pipeline. Each stage is a specialized LLM agent (or deterministic function), with a fail-fast design — if a stage fails, the pipeline stops immediately and returns a member-facing message explaining what's needed.

```
Documents + Metadata
       │
       ▼
[Stage 1] Root Agent (Gemini 2.5 Pro)
   Text extraction from PDFs/images
       │
       ▼
[Stage 2] Document Gate Agent (Gemini 2.5 Flash)          → STOP if PENDING_REUPLOAD
   Per-file classification: what type is this document?
   (PRESCRIPTION / HOSPITAL_BILL / LAB_REPORT / ...)
       │
       ▼
[Stage 3] Document Requirements Agent (Gemini 2.5 Flash)  → STOP if BLOCKED
   Does this claim have the right documents for its category?
       │
       ▼
[Stage 4] Document Extraction Agent (Gemini 2.5 Flash)
   Extract structured fields per document type
       │
       ▼
[Stage 5] Consistency Check Agent (Gemini 2.5 Flash)      → STOP if BLOCKED
   Cross-validate: same patient? dates align? amounts match?
       │
       ▼
[Stage 6] Policy Decision Engine (Pure Python, no LLM)
   7 deterministic rule checks → final decision + approved amount
```

---

## Component Breakdown

### Stage 1 — Root Agent / Orchestrator
**File**: `api/agents/agent.py`
**Model**: Gemini 2.5 Pro

This is the conductor of the entire pipeline. It receives claim metadata and uploaded file bytes, extracts plain text from each file, saves the text to in-memory artifacts, and then calls the downstream agents in strict sequence.

It owns the `PipelineTrace` output structure — a list of step results that the UI renders as a live timeline. The root agent also enforces the fail-fast contract: if any stage returns a PENDING_REUPLOAD or BLOCKED outcome, it stops the pipeline immediately and returns an actionable member message.

**Output contract (`PipelineTrace`)**:
```python
{
  "steps": [{ "step_name", "status", "summary", "key_findings" }],
  "final_status": "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW"
                | "STOPPED_AT_GATE" | "PENDING_MEMBER_ACTION",
  "final_member_message": str,   # actionable, specific
  "final_ops_summary": str,
  "blockers": [str],
  "warnings": [str],
  "policy_decision": PolicyDecision | null
}
```

---

### Stage 2 — Document Gate Agent
**File**: `api/agents/document_gate_agent/agent.py`
**Model**: Gemini 2.5 Flash

Classifies each uploaded document into one of 6 types: `PRESCRIPTION`, `HOSPITAL_BILL`, `LAB_REPORT`, `PHARMACY_BILL`, `DENTAL_REPORT`, `DISCHARGE_SUMMARY`.

The key design here is the **signal-based gate**: each document type has required signals (e.g., a PRESCRIPTION needs a doctor identifier, a diagnosis, and a medicine entry). If a document provides fewer than 2–3 required signals, it gets `gate_outcome = PENDING_REUPLOAD` with a confidence band of LOW. This prevents garbage data from flowing into extraction.

**Gate pass rules**:
- HIGH or MEDIUM confidence → PASS
- LOW confidence, UNKNOWN type, or mostly empty/garbled text → PENDING_REUPLOAD

**Required signals per type** (need ≥2–3 to PASS):

| Type | Required Signals |
|---|---|
| PRESCRIPTION | Doctor identifier, diagnosis, medicine entry |
| HOSPITAL_BILL | Bill identifier, patient name, amount |
| LAB_REPORT | Test name with result, lab ID, report date |
| PHARMACY_BILL | Pharmacy ID, medicine entry, amount |
| DENTAL_REPORT | Dental procedure/diagnosis, dentist/clinic ID |
| DISCHARGE_SUMMARY | Admission/discharge dates, final diagnosis, hospital ID |

---

### Stage 3 — Document Requirements Agent
**File**: `api/agents/document_requirements_agent/agent.py`
**Model**: Gemini 2.5 Flash

Answers: "Did the member upload the *right* documents for what they're claiming?"

Each claim category has a required document set:

| Category | Required Documents | Optional |
|---|---|---|
| CONSULTATION | PRESCRIPTION + HOSPITAL_BILL | LAB_REPORT |
| DIAGNOSTIC | PRESCRIPTION + LAB_REPORT + HOSPITAL_BILL | DISCHARGE_SUMMARY |
| PHARMACY | PRESCRIPTION + PHARMACY_BILL | — |
| DENTAL | HOSPITAL_BILL | PRESCRIPTION, DENTAL_REPORT |
| VISION | PRESCRIPTION + HOSPITAL_BILL | — |
| ALTERNATIVE_MEDICINE | PRESCRIPTION + HOSPITAL_BILL | — |

If required types are missing, it returns BLOCKED with a list of what's missing. No extraction happens until this passes.

---

### Stage 4 — Document Extraction Agent
**File**: `api/agents/document_extraction_agent/agent.py`
**Model**: Gemini 2.5 Flash

Extracts structured fields from each document, typed to the document type. It is strictly non-hallucinatory — missing fields are `null`, not guessed.

**Extracted fields by type**:

- **PRESCRIPTION**: `doctor_name`, `doctor_registration_number`, `diagnosis_primary`, `diagnosis_secondary[]`, `medicines[{name, dosage, frequency, duration}]`, `tests_ordered[]`
- **HOSPITAL_BILL**: `hospital_name`, `bill_number`, `bill_date`, `patient_name`, `line_items[{description, amount, category_hint}]`, `total_amount`
- **LAB_REPORT**: `lab_name`, `patient_name`, `report_date`, `test_results[{test_name, result_value, unit, normal_range, interpretation}]`
- **PHARMACY_BILL**: `pharmacy_name`, `bill_date`, `patient_name`, `medicines[{name, batch_no, expiry, quantity, mrp, amount}]`, `net_amount`
- **DENTAL_REPORT**: `dentist_name`, `clinic_name`, `patient_name`, `diagnosis`, `procedures_recommended_or_done[]`
- **DISCHARGE_SUMMARY**: `hospital_name`, `patient_name`, `admission_date`, `discharge_date`, `final_diagnosis`, `treatment_summary`

The `extraction_confidence` score and `missing_critical_fields[]` are passed forward so downstream stages know what to trust.

---

### Stage 5 — Consistency Check Agent
**File**: `api/agents/consistency_check_agent/agent.py`
**Model**: Gemini 2.5 Flash

Cross-validates extracted data across all documents. Receives a simplified snapshot of each document (patient name, primary date, amount, diagnosis, provider) and checks:

1. **Patient Identity** — same patient name across all documents (BLOCKER if clear mismatch)
2. **Date Consistency** — document dates vs. claimed treatment date (BLOCKER if >3 days off for primary documents)
3. **Amount Consistency** — bill totals vs. claimed amount
4. **Provider/Doctor Cross-Reference** — same providers referenced across documents
5. **Diagnosis/Procedure Alignment** — medical plausibility

Issues are tagged with severity: `INFO`, `WARNING`, or `BLOCKER`. Any BLOCKER stops the pipeline. Multiple warnings without blockers produce `MANUAL_REVIEW_RECOMMENDED`.

**Outcomes**:
- BLOCKED: Any BLOCKER-severity issue
- MANUAL_REVIEW_RECOMMENDED: Warnings but no blockers
- PASS: Info-level or no issues

---

### Stage 6 — Policy Decision Engine
**File**: `api/agents/policy_decision_agent/agent.py`
**Technology**: Pure Python, no LLM

This is the most critical design decision in the system. The policy engine is **entirely deterministic** — it is a plain Python function, not an LLM agent. This is intentional: insurance decisions must be repeatable, auditable, and legally defensible. An LLM cannot provide that guarantee.

**7 Sequential Checks**:

| Check | What It Does |
|---|---|
| `DEPENDENT_COVERAGE` | Validates the patient is a covered dependent (spouse/children/parents) |
| `MEMBER_ELIGIBILITY` | Verifies the member exists and has passed the 30-day initial waiting period |
| `WAITING_PERIODS` | Checks condition-specific waiting periods (90 days for diabetes/hypertension, 180 days for mental health, 270 days for maternity, 365 days for pre-existing, 730 days for joint replacement) |
| `EXCLUSIONS` | Matches diagnosis/procedures against policy exclusions (cosmetic, LASIK, substance abuse, self-inflicted, etc.) |
| `PRE_AUTHORIZATION` | Checks if pre-auth was required (by category, amount > threshold, or high-value imaging like MRI/CT/PET) |
| `COVERAGE_LIMITS` | Calculates approved amount with: annual OPD limit (₹50,000), per-category sub-limits (₹2,000–15,000), co-pay % (0–30%), network discounts (10–20%), family floater (₹150,000 combined), YTD utilization |
| `FRAUD_SIGNALS` | Flags abuse: >2 same-day claims, >6 monthly claims, single claim >₹25,000 → MANUAL_REVIEW |

**Amount calculation formula**:
```
base             = covered_bill_amount OR bill_total OR claimed_amount
effective_base   = base × (1 - network_discount%)   # if in-network
eligible         = min(effective_base, remaining_annual_limit)
copay            = eligible × copay_rate
approved         = eligible - copay
```

**Priority cascade** (applied to determine final decision):
- REJECTED overrides PARTIAL overrides MANUAL_REVIEW overrides APPROVED
- First FAIL → REJECTED
- First INCONCLUSIVE → MANUAL_REVIEW
- Exclusions without full coverage → PARTIAL

---

## Component Contracts

### Root Agent

**Input**:
```python
{
  "member_id": str,
  "policy_id": str,
  "claim_category": "CONSULTATION" | "DIAGNOSTIC" | "PHARMACY" | "DENTAL" | "VISION" | "ALTERNATIVE_MEDICINE",
  "treatment_date": "YYYY-MM-DD",
  "claimed_amount": float,
  "relationship_claim_type": "SELF" | "DEPENDENT",
  "patient_member_id": str | None,
  "has_pre_authorization": bool,
  "documents": [{"file_id": str, "file_name": str, "bytes": bytes, "mime_type": str}]
}
```

**Output**:
```python
{
  "steps": [{"step_name": str, "status": str, "summary": str, "key_findings": [str]}],
  "final_status": str,
  "final_member_message": str,
  "final_ops_summary": str,
  "blockers": [str],
  "warnings": [str],
  "policy_decision": PolicyDecision | None
}
```

**Errors**: Returns `final_status = "MANUAL_REVIEW"` on unrecoverable agent failure. Never crashes.

---

### Document Gate Agent

**Input**:
```python
{"file_id": str, "file_name": str, "document_text": str}
```

**Output**:
```python
{
  "file_id": str,
  "file_name": str,
  "predicted_type": str,
  "confidence_score": float,       # 0.0–1.0
  "confidence_band": "HIGH" | "MEDIUM" | "LOW",
  "extracted_signals": [str],
  "missing_required_signals": [str],
  "gate_outcome": "PASS" | "PENDING_REUPLOAD",
  "key_findings": [str],
  "ops_message": str
}
```

**Errors**: LOW confidence or empty text → `gate_outcome = PENDING_REUPLOAD` with specific member message.

---

### Document Requirements Agent

**Input**:
```python
{"claim_category": str, "predicted_types": [str]}
```

**Output**:
```python
{
  "outcome": "PASS" | "BLOCKED" | "PENDING_REUPLOAD",
  "claim_category": str,
  "required_types": [str],
  "missing_required_types": [str],
  "ops_message": str,
  "key_findings": [str]
}
```

**Errors**: Missing required document types → `outcome = BLOCKED` listing exactly what's missing.

---

### Document Extraction Agent

**Input**:
```python
{"file_id": str, "file_name": str, "document_type": str, "document_text": str}
```

**Output**:
```python
{
  "file_id": str,
  "file_name": str,
  "document_type": str,
  "extraction_confidence": float,
  "missing_critical_fields": [str],
  "prescription": {...} | None,      # populated based on document_type
  "hospital_bill": {...} | None,
  "lab_report": {...} | None,
  "pharmacy_bill": {...} | None,
  "dental_report": {...} | None,
  "discharge_summary": {...} | None,
  "extraction_notes": [str],
  "key_findings": [str],
  "ops_message": str
}
```

**Errors**: Unreadable fields → `null` values, not guesses. `missing_critical_fields` lists what couldn't be extracted.

---

### Consistency Check Agent

**Input**:
```python
{
  "claimed_amount": float | None,
  "treatment_date": "YYYY-MM-DD" | None,
  "extracted_documents": str   # JSON-serialized list of DocumentConsistencySnapshot
}
```

**DocumentConsistencySnapshot**:
```python
{
  "file_id": str, "file_name": str, "document_type": str,
  "patient_name": str | None, "primary_date": str | None,
  "amount": float | None, "diagnosis": str | None,
  "provider_name": str | None, "doctor_name": str | None
}
```

**Output**:
```python
{
  "outcome": "PASS" | "BLOCKED" | "MANUAL_REVIEW_RECOMMENDED",
  "confidence_score": float,
  "ops_message": str,
  "key_findings": [str],
  "issues": [{"issue_code": str, "severity": str, "description": str, "affected_file_names": [str], "evidence": [str]}]
}
```

---

### Policy Decision Engine

**Input**:
```python
{
  "member_id": str,
  "policy_id": str,
  "claim_category": str,
  "treatment_date": "YYYY-MM-DD",
  "claimed_amount": float,
  "has_pre_authorization": bool,
  "relationship_claim_type": str,
  "patient_member_id": str | None,
  "extracted_documents_json": str,   # JSON list of DocumentExtractionResult
  "claims_history_json": str         # JSON list, default "[]"
}
```

**Output**:
```python
{
  "decision": "APPROVED" | "PARTIAL" | "REJECTED" | "MANUAL_REVIEW",
  "approved_amount": float,
  "copay_amount": float,
  "reason": str,
  "confidence_score": float,
  "rule_findings": [{"check": str, "result": str, "detail": str, "data": dict}]
}
```

**Errors**: Pure Python — no LLM calls. Returns `MANUAL_REVIEW` if member data is missing or policy terms are unreadable.

---

## Database Schema

**PostgreSQL** (accessed via `asyncpg` for FastAPI routes, `psycopg2` in thread pool for policy checks)

```sql
-- Primary claim record
CREATE TABLE claims (
  claim_id              TEXT PRIMARY KEY,
  user_id               TEXT NOT NULL,
  session_id            TEXT NOT NULL,
  created_at            TIMESTAMPTZ NOT NULL,
  member_id             TEXT NOT NULL,
  policy_id             TEXT NOT NULL,
  claim_category        TEXT NOT NULL,
  treatment_date        DATE NOT NULL,
  claimed_amount        NUMERIC(12,2) NOT NULL,
  relationship_claim_type TEXT NOT NULL,
  patient_member_id     TEXT,
  has_pre_authorization BOOLEAN DEFAULT FALSE,
  final_status          TEXT,
  pipeline_trace        JSONB
);

-- Uploaded files stored as raw bytes
CREATE TABLE claim_documents (
  id        SERIAL PRIMARY KEY,
  claim_id  TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
  file_id   TEXT NOT NULL,
  file_name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  file_data BYTEA NOT NULL
);

-- Historical approved claims for YTD utilization calculations
CREATE TABLE claims_history (
  claim_id       TEXT PRIMARY KEY,
  member_id      TEXT NOT NULL,
  claimed_amount NUMERIC(12,2) NOT NULL,
  treatment_date DATE NOT NULL,
  is_approved    BOOLEAN DEFAULT FALSE,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_claims_member ON claims(member_id);
CREATE INDEX idx_hist_member ON claims_history(member_id);
CREATE INDEX idx_hist_date ON claims_history(treatment_date);
```

---

## API Endpoints

**Backend**: FastAPI on port 8000

| Endpoint | Method | Purpose |
|---|---|---|
| `/auth/login` | POST | Returns HMAC token + role |
| `/claims` | POST (multipart) | Submit claim + documents |
| `/claims/{id}/events` | GET (SSE) | Stream live processing events |
| `/staff/claims` | GET | List all claims (staff only) |

### SSE Endpoint Detail (`GET /claims/{id}/events`)

This is the most complex endpoint. It:
1. Fetches the claim and document bytes from the DB
2. Creates an ADK Runner session
3. Kicks off the root agent
4. Streams every ADK event (partial LLM chunks, function calls, state deltas) as `data: {...}\n\n`
5. When the agent emits a `state_delta` containing `pipeline_trace`, flattens the trace structure for direct UI consumption
6. On completion, writes `final_status` and `pipeline_trace` back to the DB

---

## UI Structure

**Stack**: React 19 + TypeScript, TanStack Router (file-based), Tailwind CSS v4 + shadcn/ui

### Routes

| Route | Purpose |
|---|---|
| `/login` | Auth (username + password) |
| `/submit` | 4-step wizard: claimant → details → documents → review |
| `/claims/:claimId` | Live processing view (SSE stream) |
| `/staff/claims` | Staff dashboard listing all claims |

### State Management

`ClaimsContext` (React context + reducer) manages all state. The reducer processes raw ADK SSE events and maintains:
- `draft`: form state for the wizard
- `active`: live claim state including `steps[]`, `finalMemberMessage`, `policyDecision`, `blockers`, `warnings`, `done`

The derived `status` field on `active` drives UI rendering: `PROCESSING` → `COMPLETED` / `BLOCKED` / `ERROR` / `PENDING_MEMBER_ACTION`.

### Key Components

| Component | Purpose |
|---|---|
| `OpsTraceTimeline` | Renders each pipeline step as a card with status badge, summary, key findings. Updates in real-time as SSE events arrive. |
| `PolicyDecisionCard` | Shows final decision, approved/copay amounts, reason text, expandable rule findings. Staff-only. |
| `MemberResultPanel` | Shows `final_member_message` and any blockers/warnings for the member. |
| `FileDropzone` | Drag-and-drop multi-file upload with MIME type and size validation (10MB limit, PDF/JPEG/PNG). |
| `WizardStepper` | Multi-step form progress indicator for the submission flow. |

---

## Data Flow

### End-to-End Claim Processing

```
UI: /submit wizard
  → POST /claims (multipart: metadata + file bytes)
    → Validate member exists in policy_terms.json
    → Validate documents (size, MIME type)
    → Store claim in DB (claims table)
    → Store documents in DB (claim_documents table)
    → Register in claims_history
    → Return {claim_id, user_id, session_id}

UI: navigate to /claims/:claimId
  → Open EventSource to GET /claims/{claimId}/events

API: SSE endpoint
  → Fetch claim + document bytes from DB
  → Create ADK Runner session
  → Prepare metadata + file bytes as Content
  → Kick off Root Agent

Root Agent streams:
  [Stage 2] Document gate per file       → STOP if PENDING_REUPLOAD
  [Stage 3] Requirements check           → STOP if BLOCKED
  [Stage 4] Extraction per file
  [Stage 5] Consistency check            → STOP if BLOCKED
  [Stage 6] Policy decision              → final decision + amounts

API flattens state_delta → sends to UI as SSE
UI reducer updates steps[], status, policyDecision in real-time
API writes final_status + pipeline_trace back to DB on completion
```

### Trace Flattening

The root agent emits a `state_delta` containing the full nested `PipelineTrace`. The SSE endpoint flattens it for the UI:

```python
# Raw from agent state_delta:
{
  "pipeline_trace": {
    "steps": [...],
    "final_status": "APPROVED",
    "final_member_message": "...",
    "policy_decision": {...}
  }
}

# Flattened for UI consumption:
{
  "final_status": "APPROVED",
  "final_member_message": "...",
  "policy_decision": {...},
  "blockers": [...],
  "warnings": [...],
  "DOCUMENT_CLASSIFICATION": {"status": "COMPLETED", "summary": "...", "key_findings": [...]},
  "DOCUMENT_REQUIREMENTS": {...},
  "DOCUMENT_EXTRACTION": {...},
  "CONSISTENCY_CHECK": {...},
  "POLICY_DECISION": {...}
}
```

---

## External Integrations

| Service | Purpose |
|---|---|
| Google Gemini (Vertex AI) | LLM inference — `gemini-2.5-pro` for orchestrator, `gemini-2.5-flash` for all sub-agents |
| Google ADK | Agent runtime: `LlmAgent`, `AgentTool`, `Runner`, sessions, artifacts |
| Google Cloud Run | Serverless container hosting (API + UI) |
| Google Cloud SQL | Managed PostgreSQL |
| Google Artifact Registry | Docker image storage |
| Google Secret Manager | `DATABASE_URL` and other secrets |
| Google Cloud Trace | Distributed tracing for agent calls (optional, graceful degradation) |
| Workload Identity Federation | Keyless auth for CI/CD (no service account JSON) |

---

## Deployment Architecture

```
GitHub Push to main
       │
       ▼
Cloud Build CI/CD
  ├── Build API image  (Python 3.11 slim)
  └── Build UI image   (Node 20 → server.mjs HTTP wrapper)
       │
       ▼
Artifact Registry (Docker images)
       │
  ┌────┴────┐
  ▼         ▼
API          UI
Cloud Run    Cloud Run
2Gi / 2CPU  512Mi / 1CPU
max 10       max 5
instances    instances
  │
  └── Cloud SQL Proxy → PostgreSQL (claims_db)
```

The UI is built as a TanStack Start SSR app, compiled with Vite's Cloudflare adapter, then wrapped in a `server.mjs` Node.js HTTP server (because Cloud Run needs a Node process, not just static files).

---

## What Was Considered and Rejected

### 1. LLM-Based Policy Engine
**Considered**: Let Gemini evaluate policy rules from `policy_terms.json`.
**Rejected**: Insurance decisions must be repeatable and auditable. LLMs can hallucinate coverage amounts, misread limits, and produce different answers for the same inputs. A missed exclusion could mean paying a fraudulent claim.
**Chosen**: Pure Python function with explicit rule checks and formula-based math.
---

## Limitations and Scaling Plan

### 1. No Per-Agent Retry
If one agent call fails (Gemini timeout, malformed response), the entire pipeline fails with a generic error.

**At 10x load**: Add per-agent retry with exponential backoff. Soft-fail non-critical stages (e.g., consistency check) to `MANUAL_REVIEW` rather than stopping the pipeline entirely.

---

## Summary Table

| Component | Technology | Model / Runtime | Role |
|---|---|---|---|
| Root Agent | ADK LlmAgent | Gemini 2.5 Pro | Pipeline orchestration, OCR, trace emission |
| Document Gate | ADK LlmAgent | Gemini 2.5 Flash | Per-file classification and gate evaluation |
| Requirements | ADK LlmAgent | Gemini 2.5 Flash | Claim-level document completeness check |
| Extraction | ADK LlmAgent | Gemini 2.5 Flash | Structured field extraction (100+ fields) |
| Consistency Check | ADK LlmAgent | Gemini 2.5 Flash | Cross-document validation |
| Policy Engine | Pure Python | n/a | 7 deterministic rule checks, amount calculation |
| Database | PostgreSQL | asyncpg + psycopg2 | Claim records, documents, history |
| API | FastAPI | Uvicorn | REST endpoints + SSE streaming |
| UI | React + TanStack | Node.js (Cloud Run) | Submission wizard + live trace view |
| CI/CD | Cloud Build + GitHub Actions | — | Build, push, deploy to Cloud Run |

---

## Core Design Philosophy

**LLMs for understanding, Python for decisions.**

The LLMs handle the parts that require reading, interpreting, and classifying noisy real-world documents. The moment a number needs to be committed — "we approve ₹4,200" — it is computed by deterministic code against explicit rules, with a full audit trail. This combination gives the system the flexibility to handle messy inputs while maintaining the repeatability and auditability that insurance adjudication requires.
