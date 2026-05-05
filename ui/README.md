# Health Insurance Claims Intake + Review

A two-page React UI for ops teams to submit health insurance claims and watch the backend process them in real time via Server-Sent Events.

The product scope ends at the **document consistency check** stage. Policy validation UI is intentionally deferred.

## Tech Stack

- React 19 + TypeScript
- Vite + TanStack Start (file-based routing under `src/routes/`)
- Tailwind CSS v4
- shadcn/ui primitives
- React Context + reducer for state (`src/context/ClaimsContext.tsx`)
- Native `fetch` for REST and `EventSource` for SSE

## Local Development

```bash
bun install
bun run dev
```

Open http://localhost:5173 — the root path redirects to `/submit`.

## Environment Variables

Create a `.env.local` (or `.env`) at the project root:

```
VITE_API_BASE_URL=http://localhost:8000
```

Defaults to `http://localhost:8000` if unset.

## Backend Contract

The UI assumes a backend exposing:

### `POST /claims` — multipart/form-data

| Field | Type | Notes |
|---|---|---|
| `member_id` | string | required |
| `policy_id` | string | required |
| `claim_category` | enum | `CONSULTATION` \| `DIAGNOSTIC` \| `PHARMACY` \| `DENTAL` \| `VISION` \| `ALTERNATIVE_MEDICINE` |
| `treatment_date` | string | `YYYY-MM-DD` |
| `claimed_amount` | number | > 0 |
| `relationship_claim_type` | enum | `SELF` \| `DEPENDENT` |
| `patient_member_id` | string | required only if `DEPENDENT` |
| `documents` | file[] | pdf / jpg / png |

Response:
```json
{ "claim_id": "CLM_xxx", "user_id": "user_xxx", "session_id": "sess_xxx" }
```

### `GET /claims/{claim_id}/events` — text/event-stream

Each message is `data: <json>\n\n`. Three event shapes are handled:

1. **ADK event** — streamed agent text + `actions.state_delta`. Partial chunks (`partial: true`) append to the live message; `is_final_response: true` replaces it. State-delta keys whose value contains a `status` field are rendered as ops-trace steps. Recognised step keys: `DOCUMENT_CLASSIFICATION`, `DOCUMENT_REQUIREMENTS`, `DOCUMENT_EXTRACTION`, `CONSISTENCY_CHECK`. The UI also surfaces `final_member_message`, `blockers`, `warnings`, and `handoff_payload` from the state delta.
2. **`type: "pipeline_completion"`** — closes the stream and marks the claim Completed.
3. **`type: "error"`** — closes the stream and shows a red error banner.

## Pages

- **`/submit`** — 4-step wizard: Claimant → Details → Documents → Review & Submit.
- **`/claims/:claimId`** — Two-column live view: member-facing message (left) + ops trace timeline (right). Includes a "Download trace JSON" button that exports every received SSE payload.

## Project Structure

```
src/
  routes/
    __root.tsx          # Provider + shell
    index.tsx           # Redirects to /submit
    submit.tsx          # Wizard
    claims.$claimId.tsx # Live processing view
  context/
    ClaimsContext.tsx   # Draft + active-claim state
  lib/
    claims-types.ts     # Shared types & enums
    claims-api.ts       # createClaim() + eventsUrl()
  components/claims/    # Wizard steps, trace timeline, status badges, etc.
```

## Out of Scope

- Policy validation step in the timeline (planned for a later iteration)
- Authentication
- Persisting drafts across reloads
