from __future__ import annotations

import json
import logging
import os
import pathlib
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional
import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel as PydanticBaseModel

from auth import authenticate, create_token, verify_token

from ocr.service import OcrBatchResult, extract_text_for_documents
from pipeline.orchestrator import run_claim_pipeline
import asyncio
import db

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cloud Trace — initialize once at startup so every agent invocation emits
# spans to Google Cloud Trace (project set via GOOGLE_CLOUD_PROJECT env var).
# ---------------------------------------------------------------------------
try:
    from google.adk.telemetry.google_cloud import get_gcp_exporters as _get_gcp_exporters
    from google.adk.telemetry.google_cloud import get_gcp_resource as _get_gcp_resource
    from google.adk.telemetry.setup import maybe_set_otel_providers as _maybe_set_otel_providers

    _gcp_project = os.getenv("GOOGLE_CLOUD_PROJECT")
    _otel_hooks = _get_gcp_exporters(enable_cloud_tracing=True)
    _otel_resource = _get_gcp_resource(project_id=_gcp_project)
    _maybe_set_otel_providers(otel_hooks_to_setup=[_otel_hooks], otel_resource=_otel_resource)
    logger.info("Cloud Trace initialized for project=%s", _gcp_project)
except Exception as _otel_exc:
    logger.warning("Cloud Trace setup failed (traces won't be exported): %s", _otel_exc)

APP_NAME = "claims_pipeline"

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}

# ---------------------------------------------------------------------------
# Policy terms — loaded once at startup; fails fast if file is missing.
# ---------------------------------------------------------------------------
_POLICY_TERMS_PATH = pathlib.Path(os.getenv("POLICY_TERMS_PATH", str(pathlib.Path(__file__).parent / "policy_terms.json")))
if not _POLICY_TERMS_PATH.exists():
    _POLICY_TERMS_PATH = pathlib.Path(__file__).parent.parent / "policy_terms.json"
try:
    with open(_POLICY_TERMS_PATH) as _f:
        _POLICY_TERMS: dict[str, Any] = json.load(_f)
except FileNotFoundError:
    logger.critical("policy_terms.json not found at %s — cannot start.", _POLICY_TERMS_PATH)
    raise

FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173,http://localhost:8080")
ALLOWED_ORIGINS = [o.strip() for o in FRONTEND_BASE_URL.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://localhost:8080",
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await db.init_pool()
    yield
    await db.close_pool()

app = FastAPI(title="Claims Flow API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    # Allow common local-network dev origins (e.g. http://192.168.x.x:8080)
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LoginRequest(PydanticBaseModel):
    username: str
    password: str


def _get_auth_payload(authorization: Optional[str] = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(authorization.split(" ", 1)[1])
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


def _require_staff(payload: dict = Depends(_get_auth_payload)) -> dict:
    if payload.get("role") != "staff":
        raise HTTPException(status_code=403, detail="Staff access required")
    return payload


@app.post("/auth/login")
async def login(req: LoginRequest):
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(sub=user["sub"], role=user["role"], name=user["name"])
    return {"token": token, "role": user["role"], "name": user["name"], "sub": user["sub"]}


@app.get("/staff/claims")
async def get_all_claims(_payload: dict = Depends(_require_staff)):
    claims = await db.get_all_claims_for_staff()
    return {"claims": claims}


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "claims-flow-api"}


def _lookup_member(member_id: str) -> dict[str, Any] | None:
    """Return the member dict from policy_terms.json or None if not found."""
    for m in _POLICY_TERMS.get("members", []):
        if m.get("member_id") == member_id:
            return m
    return None


OCR_UNAVAILABLE_STATUS = "MANUAL_REVIEW"


def build_documents_with_text(
    documents: list[dict[str, Any]], batch: OcrBatchResult
) -> list[dict[str, Any]]:
    """Build the TEXT-ONLY per-document payload for the pipeline.

    Privacy invariant: the returned items carry only file_id/file_name/document_text —
    never image bytes. Image bytes go only to the self-hosted OCR service.
    """
    text_by_id = {r.file_id: r.document_text for r in batch.results}
    return [
        {
            "file_id": d["file_id"],
            "file_name": d["file_name"],
            "document_text": text_by_id.get(d["file_id"], ""),
        }
        for d in documents
    ]


def pipeline_event_to_sse(
    event: dict[str, Any], claim_id: str, user_id: str, session_id: str
) -> dict[str, Any]:
    """Wrap an orchestrator event in the SSE envelope the UI expects."""
    return {
        "type": event.get("type", "stage"),
        "author": "claims_pipeline_agent",
        "actions": {"state_delta": event.get("state_delta", {})},
        "claim_id": claim_id,
        "user_id": user_id,
        "session_id": session_id,
        "created_at": _now_iso(),
    }


def ocr_step_event(claim_id: str, user_id: str, session_id: str, batch: OcrBatchResult) -> dict:
    """Synthetic SSE event so the UI shows a TEXT_EXTRACTION step (UI heuristic:
    any state_delta key with a `status` field is rendered as a trace step)."""
    ok = [r for r in batch.results if r.ok]
    failed = [r for r in batch.results if not r.ok]
    findings = [f"{r.file_name}: {len(r.document_text)} chars" for r in ok]
    findings += [f"{r.file_name}: unreadable" for r in failed]
    return {
        "type": "ocr_status",
        "author": "ocr_prestage",
        "actions": {"state_delta": {"TEXT_EXTRACTION": {
            "status": "COMPLETED",
            "summary": f"Extracted text from {len(ok)}/{len(batch.results)} document(s) via self-hosted OCR.",
            "key_findings": findings[:5],
        }}},
        "claim_id": claim_id,
        "user_id": user_id,
        "session_id": session_id,
        "created_at": _now_iso(),
    }


@app.post("/claims")
async def create_claim(
    member_id: str = Form(...),
    policy_id: str = Form(...),
    claim_category: str = Form(...),
    treatment_date: str = Form(...),
    claimed_amount: float = Form(...),
    relationship_claim_type: str = Form(...),
    patient_member_id: Optional[str] = Form(None),
    has_pre_authorization: bool = Form(False),
    documents: list[UploadFile] = [],
):
    if not documents:
        raise HTTPException(status_code=400, detail="At least one document is required.")

    member = _lookup_member(member_id)
    if member is None:
        raise HTTPException(
            status_code=422,
            detail=f"Member '{member_id}' not found in policy '{policy_id}'. Please check the member ID.",
        )

    claim_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)

    inp = {
        "member_id": member_id,
        "policy_id": policy_id,
        "claim_category": claim_category,
        "treatment_date": treatment_date,
        "claimed_amount": claimed_amount,
        "relationship_claim_type": relationship_claim_type,
        "patient_member_id": patient_member_id,
        "has_pre_authorization": has_pre_authorization,
    }

    await db.insert_claim(claim_id, user_id, session_id, created_at, inp)

    for index, file in enumerate(documents, start=1):
        data = await file.read()
        if not data:
            continue
        if len(data) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"'{file.filename}' exceeds the 10 MB file size limit.",
            )
        mime = (file.content_type or "").lower()
        if mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"'{file.filename}' has unsupported type '{mime}'. Upload PDF, JPEG, or PNG only.",
            )
        await db.insert_document(
            claim_id,
            f"F{index:03d}",
            file.filename or f"upload-{index}",
            mime,
            data,
        )

    await db.db_register_claim(
        claim_id=claim_id,
        member_id=member_id,
        claimed_amount=claimed_amount,
        treatment_date=treatment_date,
    )

    return JSONResponse({"claim_id": claim_id, "user_id": user_id, "session_id": session_id})


@app.get("/claims/{claim_id}/events")
async def claim_events(claim_id: str):
    async def event_generator():
        claim = await db.get_claim_with_documents(claim_id)
        if not claim:
            error_event = {
                "type": "error",
                "message": "Claim not found.",
                "code": 4040,
                "claim_id": claim_id,
                "created_at": _now_iso(),
            }
            yield f"data: {json.dumps(error_event)}\n\n"
            return

        user_id = claim["user_id"]
        session_id = claim["session_id"]
        claim_input = {
            "member_id": claim["member_id"],
            "policy_id": claim["policy_id"],
            "claim_category": claim["claim_category"],
            "treatment_date": str(claim["treatment_date"]),
            "claimed_amount": float(claim["claimed_amount"]),
            "relationship_claim_type": claim["relationship_claim_type"],
            "patient_member_id": claim.get("patient_member_id"),
            "has_pre_authorization": claim.get("has_pre_authorization", False),
        }
        documents = claim["documents"]

        # OCR pre-stage: extract text from images/PDFs via the self-hosted VLM.
        # Runs off the event loop so a slow/blocking VLM call never stalls the app.
        batch = await asyncio.to_thread(extract_text_for_documents, documents)

        # Stream a synthetic TEXT_EXTRACTION step so the UI timeline is unchanged.
        yield f"data: {json.dumps(ocr_step_event(claim_id, user_id, session_id, batch))}\n\n"

        # If the OCR service was entirely unreachable, this is an outage, not a
        # member problem: route to manual review instead of asking for re-uploads.
        if batch.service_unavailable:
            await db.update_claim_final(claim_id, OCR_UNAVAILABLE_STATUS, None)
            outage_event = {
                "type": "error",
                "message": "We are processing your claim. A specialist will review it shortly.",
                "ops_detail": "OCR service unavailable — claim queued for manual review.",
                "final_status": OCR_UNAVAILABLE_STATUS,
                "claim_id": claim_id,
                "user_id": user_id,
                "session_id": session_id,
                "created_at": _now_iso(),
            }
            yield f"data: {json.dumps(outage_event)}\n\n"
            return

        # Build the TEXT-ONLY pipeline input (no image bytes ever reach the LLM stages).
        documents_with_text = build_documents_with_text(documents, batch)
        claim_pipeline_input = {
            **claim_input,
            "claim_id": claim_id,
            "claims_history": claim.get("claims_history", []),
        }
        logger.info("[SSE] claim_id=%s docs=%d", claim_id, len(documents))

        try:
            final_trace = None
            async for ev in run_claim_pipeline(claim_pipeline_input, documents_with_text):
                sse = pipeline_event_to_sse(ev, claim_id, user_id, session_id)
                yield f"data: {json.dumps(sse)}\n\n"
                if ev.get("type") == "final":
                    final_trace = ev.get("trace")

            try:
                final_status = (final_trace or {}).get("final_status")
                await db.update_claim_final(claim_id, final_status, final_trace)
                if final_status in ("APPROVED", "PARTIAL"):
                    await db.db_mark_claim_approved(claim_id)
            except Exception as wb_exc:
                logger.warning("Write-back failed for claim %s: %s", claim_id, wb_exc)

            completion_event = {
                "type": "pipeline_completion",
                "author": "claims_pipeline_agent",
                "content": {"parts": [{"text": "Claim processing completed"}]},
                "pipeline_complete": True,
                "claim_id": claim_id,
                "user_id": user_id,
                "session_id": session_id,
                "created_at": _now_iso(),
            }
            yield f"data: {json.dumps(completion_event)}\n\n"

        except Exception as exc:
            logger.exception("SSE processing error: %s", exc)
            error_event = {
                "type": "error",
                "message": "An error occurred while processing the claim. Please try again.",
                "code": 5001,
                "claim_id": claim_id,
                "user_id": user_id,
                "session_id": session_id,
                "created_at": _now_iso(),
            }
            yield f"data: {json.dumps(error_event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":

    uvicorn.run(app, host="0.0.0.0", port=8000)
