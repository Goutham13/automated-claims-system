# Plum Health Insurance Claims Processing System

An AI-driven pipeline that automates end-to-end health insurance claim adjudication — from document upload to a fully traceable `APPROVED / PARTIAL / REJECTED / MANUAL_REVIEW` decision — while keeping deterministic Python in charge of all financial decisions.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Backend](#backend)
  - [Frontend](#frontend)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Pipeline Stages](#pipeline-stages)
- [Policy Rules](#policy-rules)
- [Deployment](#deployment)
- [CI/CD](#cicd)
- [Testing](#testing)

---

## Overview

Manual claim review doesn't scale. This system automates the full adjudication lifecycle:

1. An employee submits a claim with medical documents (bills, prescriptions, lab reports).
2. A 6-stage multi-agent pipeline validates, classifies, extracts, cross-checks, and applies policy rules.
3. A real-time UI shows the member a plain-language status update and shows ops staff the full pipeline trace.

**Core design principle — _LLMs for understanding, Python for decisions_:**
- LLMs read, interpret, and classify noisy real-world documents (handwriting, stamps, phone photos).
- The moment a number is committed ("we approve ₹4,200"), it is computed by deterministic code against explicit rules with a full audit trail.

---

## Architecture

```
                          ┌──────────────────────────────────────────────────────┐
                          │                  FastAPI Backend                      │
                          │                                                      │
  Member/Staff ──HTTP──▶  │  POST /claims ──▶ Root Orchestrator (Gemini 2.5 Pro) │
                          │                         │                            │
                          │                         ▼                            │
                          │                  Document Gate Agent                 │
                          │                    (Flash 2.5)                       │
                          │                         │                            │
                          │                         ▼                            │
                          │             Document Requirements Agent              │
                          │                    (Flash 2.5)                       │
                          │                         │                            │
                          │                         ▼                            │
                          │              Document Extraction Agent               │
                          │                    (Flash 2.5)                       │
                          │                         │                            │
                          │                         ▼                            │
                          │              Consistency Check Agent                 │
                          │                  (Flash 2.5)                         │
                          │                         │                            │
                          │                         ▼                            │
                          │           Policy Decision Engine (pure Python)       │
                          │                         │                            │
                          │                         ▼                            │
                          │            PostgreSQL  (claims, documents, history)  │
                          └──────────────────────────────────────────────────────┘
                                        │ SSE /claims/:id/events
                                        ▼
                             TanStack Start (React 19) UI
                             ├── /submit  — 4-step claim wizard
                             ├── /claims/:id — real-time status view
                             └── /staff/claims — ops dashboard
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design document and [`docs/COMPONENT_CONTRACTS.md`](docs/COMPONENT_CONTRACTS.md) for API and agent contracts.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend language** | Python 3.11+ |
| **API framework** | FastAPI + Uvicorn |
| **AI orchestration** | Google ADK (Agent Development Kit) |
| **LLM models** | Gemini 2.5 Pro (orchestrator), Gemini 2.5 Flash (agents) |
| **LLM provider** | Vertex AI |
| **Database** | PostgreSQL (asyncpg for async routes, psycopg2 for sync policy engine) |
| **Frontend framework** | React 19 + TypeScript |
| **Frontend build** | Vite + TanStack Start |
| **Routing** | TanStack Router (file-based) |
| **Styling** | Tailwind CSS v4 + shadcn/ui + Radix UI |
| **Package manager (UI)** | npm |
| **Package manager (API)** | uv |
| **Container runtime** | Docker → Google Cloud Run |
| **CI/CD** | GitHub Actions + Google Cloud Build |
| **Auth to GCP** | Workload Identity Federation (keyless) |
| **Secrets** | Google Secret Manager |

---

## Project Structure

```
plum-assessment-trial/
├── api/                          # Python FastAPI backend
│   ├── main.py                   # App entrypoint, all HTTP/SSE endpoints
│   ├── agents/
│   │   ├── agent.py              # Root orchestrator agent
│   │   ├── document_gate_agent/
│   │   ├── document_requirements_agent/
│   │   ├── document_extraction_agent/
│   │   ├── consistency_check_agent/
│   │   └── policy_decision_agent/
│   ├── db.py                     # PostgreSQL connection pool
│   ├── models.py                 # Pydantic request/response models
│   ├── requirements.txt
│   └── Dockerfile
├── ui/                           # React 19 + TypeScript frontend
│   ├── app/
│   │   ├── routes/               # File-based routes
│   │   │   ├── submit.tsx        # Claim submission wizard
│   │   │   ├── claims.$claimId.tsx  # Real-time claim status
│   │   │   └── staff.claims.tsx  # Ops dashboard
│   │   └── components/           # Shared UI components
│   ├── package.json
│   ├── vite.config.ts
│   └── Dockerfile
├── docs/
│   ├── ARCHITECTURE.md           # Full system design
│   └── COMPONENT_CONTRACTS.md    # Agent and API contracts
├── .github/workflows/
│   ├── deploy-api.yml
│   └── deploy-ui.yml
├── cloudbuild.yaml               # Cloud Build orchestration
├── policy_terms.json             # Policy rules, member roster, exclusions
├── test_cases.json               # 12 evaluation test cases
└── assignment.md                 # Original problem statement
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- [Bun](https://bun.sh/) (for the frontend)
- PostgreSQL 14+ (or Docker)
- A Google Cloud project with Vertex AI API enabled
- ADC (Application Default Credentials): run `gcloud auth application-default login`

### Backend

```bash
cd api

# Install dependencies
uv sync

# Configure environment variables (see section below)
cp .env.example .env  # then edit .env

# Apply database migrations (creates tables on first run)
# Tables are auto-created by main.py on startup via db.py

# Start the API server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### Frontend

```bash
cd ui

# Install dependencies
npm install

# Start the dev server
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

UI will be available at `http://localhost:5173` (auto-redirects to `/submit`).

---

## Environment Variables

### API

| Variable | Required | Description | Example |
|---|---|---|---|
| `GOOGLE_GENAI_USE_VERTEXAI` | Yes | Use Vertex AI as the LLM provider | `TRUE` |
| `GOOGLE_CLOUD_PROJECT` | Yes | GCP project ID | `my-project-id` |
| `GOOGLE_CLOUD_LOCATION` | Yes | Vertex AI region | `global` |
| `DATABASE_URL` | Yes | PostgreSQL connection string | `postgresql://user:pass@localhost:5432/claims` |
| `FRONTEND_BASE_URL` | No | CORS allowed origins (comma-separated) | `http://localhost:5173` |
| `POLICY_TERMS_PATH` | No | Path to `policy_terms.json` | Auto-discovered from repo root |
| `MEMBER_PASSWORD` | No | Password for member auth | `member123` |
| `STAFF_USERNAME` | No | Username for staff auth | `staff` |
| `STAFF_PASSWORD` | No | Password for staff auth | `staff@123` |

### UI

| Variable | Required | Description | Example |
|---|---|---|---|
| `VITE_API_BASE_URL` | No | API base URL (baked in at build time) | `http://localhost:8000` |

---

## API Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | None | Obtain a session token (member or staff) |
| `POST` | `/claims` | Member token | Submit a new claim with documents (multipart/form-data) |
| `GET` | `/claims/{claim_id}/events` | Member/Staff token | SSE stream of pipeline events for a claim |
| `GET` | `/staff/claims` | Staff token | List all claims with status and summary |

SSE events emitted during pipeline execution:

- `pipeline_start` — claim received, pipeline begins
- `stage_update` — one pipeline stage completed (includes stage name, status, summary, key findings)
- `pipeline_complete` — final decision ready (includes `decision`, `approved_amount`, `reason`)
- `pipeline_error` — unrecoverable error with message

---

## Pipeline Stages

The pipeline runs 6 stages in strict sequence, failing fast on blockers:

| # | Stage | Model | Purpose |
|---|---|---|---|
| 1 | **Document Gate** | Gemini 2.5 Flash | Classifies each uploaded file; rejects unrecognizable documents |
| 2 | **Document Requirements** | Gemini 2.5 Flash | Validates the claim has the correct document types for its category |
| 3 | **Document Extraction** | Gemini 2.5 Flash | Extracts 100+ structured fields from each document |
| 4 | **Consistency Check** | Gemini 2.5 Flash | Cross-validates patient identity, dates, amounts, provider references across documents |
| 5 | **Policy Decision** | Pure Python | Applies 7 deterministic policy rules (see below) |

Possible pipeline outcomes:

| Decision | Meaning |
|---|---|
| `APPROVED` | Claim passes all checks; full approved amount returned |
| `PARTIAL` | Claim passes but amount is reduced (sub-limits, copay, network discount) |
| `REJECTED` | Claim blocked by a policy rule (exclusion, waiting period, ineligibility) |
| `MANUAL_REVIEW` | Consistency issues or fraud signals require human review |
| `PENDING_REUPLOAD` | Documents missing or unrecognizable; member prompted to re-upload |

---

## Policy Rules

The Policy Decision Engine applies 7 sequential deterministic checks (all logic in `api/agents/policy_decision_agent/`):

1. **Dependent Coverage** — validates the claimant is a covered dependent
2. **Member Eligibility** — enforces the 30-day initial waiting period post-enrollment
3. **Waiting Periods** — condition-specific waiting periods:
   - Diabetes: 90 days
   - Mental health: 180 days
   - Maternity: 270 days
   - Pre-existing conditions: 365 days
   - Joint replacement: 730 days
4. **Exclusions** — matches diagnosis/procedures against policy exclusions list
5. **Pre-Authorization** — verifies pre-auth was obtained when required
6. **Coverage Limits** — calculates approved amount applying OPD annual limits, procedure sub-limits, copay %, in-network discounts, and family floater deductions
7. **Fraud Signals** — flags patterns: > 2 same-day claims, > 6 claims per month, single claim > ₹25,000

Policy configuration lives in [`policy_terms.json`](policy_terms.json).

---

## Deployment

Both services deploy to **Google Cloud Run** as Docker containers.

### Prerequisites

- Google Cloud project with the following APIs enabled:
  - Vertex AI, Cloud Run, Artifact Registry, Secret Manager, Cloud SQL (optional)
- A PostgreSQL instance (Cloud SQL recommended for production)
- `DATABASE_URL` stored in Secret Manager

### Manual deploy (API)

```bash
# Build and push image
gcloud builds submit api/ --tag gcr.io/$PROJECT_ID/claims-api

# Deploy to Cloud Run
gcloud run deploy claims-api \
  --image gcr.io/$PROJECT_ID/claims-api \
  --region us-central1 \
  --memory 2Gi \
  --cpu 2 \
  --max-instances 10 \
  --set-secrets DATABASE_URL=DATABASE_URL:latest \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=global
```

### Manual deploy (UI)

```bash
# Build and push image
gcloud builds submit ui/ --tag gcr.io/$PROJECT_ID/claims-ui

# Deploy to Cloud Run
gcloud run deploy claims-ui \
  --image gcr.io/$PROJECT_ID/claims-ui \
  --region us-central1 \
  --memory 512Mi \
  --cpu 1 \
  --max-instances 5 \
  --set-env-vars VITE_API_BASE_URL=https://<api-cloud-run-url>
```

Or use **Cloud Build** to orchestrate both in one step:

```bash
gcloud builds submit --config cloudbuild.yaml
```

---

## CI/CD

Push to `main` triggers automatic deployments via GitHub Actions:

| Workflow | Trigger | Deploys |
|---|---|---|
| `.github/workflows/deploy-api.yml` | Changes in `api/**` or `policy_terms.json` | API → Cloud Run |
| `.github/workflows/deploy-ui.yml` | Changes in `ui/**` | UI → Cloud Run |

Authentication uses **Workload Identity Federation** — no service account JSON keys are stored in GitHub secrets.

Required GitHub repository secrets/variables:

- `GCP_PROJECT_ID` — your GCP project ID
- `WIF_PROVIDER` — Workload Identity Federation provider resource name
- `WIF_SERVICE_ACCOUNT` — service account email for impersonation
- `ARTIFACT_REGISTRY_REPO` — Artifact Registry repo URL

---
