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

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.artifacts import InMemoryArtifactService
from google.adk.sessions import InMemorySessionService
from google.genai.types import Content, Part

from agents.agent import root_agent
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

session_service = InMemorySessionService()
artifact_service = InMemoryArtifactService()


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


def _is_partial_tool_only_event(event_data: dict[str, Any]) -> bool:
    """Return True for partial=True streaming events that carry only function_call parts.

    ADK emits these as mid-generation chunks before the committed (partial=False) version
    of the same tool call arrives. The committed event is authoritative; the streaming
    chunk adds no new information and should not be forwarded to the UI.
    """
    if not event_data.get("partial"):
        return False
    parts = (event_data.get("content") or {}).get("parts") or []
    if not parts:
        return False
    return all(
        p.get("function_call") is not None or p.get("function_response") is not None
        for p in parts
    )


def _flatten_pipeline_trace_state_delta(state_delta: dict[str, Any]) -> dict[str, Any]:
    """Convert {"pipeline_trace": {...}} to a UI-friendly flat state_delta."""
    flattened: dict[str, Any] = dict(state_delta)
    trace = state_delta.get("pipeline_trace")
    if not isinstance(trace, dict):
        return flattened

    # Preserve any other state updates produced during the same invocation (e.g. tools).
    flattened = {k: v for k, v in flattened.items() if k != "pipeline_trace"}
    flattened["final_member_message"] = trace.get("final_member_message")
    flattened["final_ops_summary"] = trace.get("final_ops_summary")
    flattened["final_status"] = trace.get("final_status")
    flattened["blockers"] = trace.get("blockers", [])
    flattened["warnings"] = trace.get("warnings", [])
    flattened["handoff_payload"] = trace.get("handoff_payload", {})

    # Forward policy_decision so the UI can render the decision card.
    if trace.get("policy_decision") is not None:
        flattened["policy_decision"] = trace["policy_decision"]

    steps = trace.get("steps", [])
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_name = step.get("step_name")
            if not isinstance(step_name, str) or not step_name:
                continue
            flattened[step_name] = {
                "status": step.get("status"),
                "summary": step.get("summary"),
                "key_findings": step.get("key_findings", []),
                "ops_message": step.get("ops_message"),
                "member_message": step.get("member_message"),
            }

    return flattened


async def _start_session(*, user_id: str, session_id: Optional[str]) -> tuple[Runner, Any, RunConfig]:
    runner = Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=session_service,
        artifact_service=artifact_service,
    )

    session = None
    if session_id:
        session = await runner.session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    if session is None:
        session = await runner.session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)

    run_config = RunConfig(
        streaming_mode=StreamingMode.SSE,
        response_modalities=["TEXT"],
        max_llm_calls=500,
    )
    return runner, session, run_config


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "claims-flow-api"}


def _lookup_member(member_id: str) -> dict[str, Any] | None:
    """Return the member dict from policy_terms.json or None if not found."""
    for m in _POLICY_TERMS.get("members", []):
        if m.get("member_id") == member_id:
            return m
    return None


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

        runner, session, run_config = await _start_session(user_id=user_id, session_id=session_id)

        metadata = {
            "claim_id": claim_id,
            **claim_input,
            "documents": [
                {"file_id": d["file_id"], "file_name": d["file_name"], "mime_type": d["mime_type"]}
                for d in documents
            ],
        }

        parts: list[Part] = [Part.from_text(text="Process this claim intake request:\n" + json.dumps(metadata))]
        for d in documents:
            parts.append(Part.from_bytes(data=d["bytes"], mime_type=d["mime_type"]))

        content = Content(role="user", parts=parts)
        logger.info("[SSE] claim_id=%s user_id=%s session_id=%s", claim_id, user_id, session_id)

        try:
            async for event in runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=content,
                run_config=run_config,
            ):
                event_data = json.loads(event.model_dump_json())
                event_data["is_final_response"] = event.is_final_response()
                event_data["created_at"] = _now_iso()
                event_data["user_id"] = session.user_id
                event_data["session_id"] = session.id
                event_data["claim_id"] = claim_id

                if _is_partial_tool_only_event(event_data):
                    continue

                state_delta = event_data.get("actions", {}).get("state_delta")
                if isinstance(state_delta, dict) and state_delta:
                    event_data.setdefault("actions", {})
                    event_data["actions"]["state_delta"] = _flatten_pipeline_trace_state_delta(state_delta)

                yield f"data: {json.dumps(event_data)}\n\n"

            try:
                session_state = await runner.session_service.get_session(
                    app_name=APP_NAME, user_id=user_id, session_id=session_id
                )
                if session_state:
                    trace = session_state.state.get("pipeline_trace") or {}
                    final_status = trace.get("final_status") if isinstance(trace, dict) else None
                    await db.update_claim_final(claim_id, final_status, trace if isinstance(trace, dict) else None)
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
