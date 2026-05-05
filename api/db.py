"""Async PostgreSQL pool for FastAPI routes (asyncpg)."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any

import asyncpg

_pool: asyncpg.Pool | None = None


async def init_pool() -> None:
    global _pool
    _pool = await asyncpg.create_pool(os.getenv("DATABASE_URL"), min_size=2, max_size=10)
    await _create_tables()


async def close_pool() -> None:
    if _pool:
        await _pool.close()


async def _create_tables() -> None:
    assert _pool
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                claim_id              TEXT PRIMARY KEY,
                user_id               TEXT          NOT NULL,
                session_id            TEXT          NOT NULL,
                created_at            TIMESTAMPTZ   NOT NULL,
                member_id             TEXT          NOT NULL,
                policy_id             TEXT          NOT NULL,
                claim_category        TEXT          NOT NULL,
                treatment_date        DATE          NOT NULL,
                claimed_amount        NUMERIC(12,2) NOT NULL,
                relationship_claim_type TEXT        NOT NULL,
                patient_member_id     TEXT,
                has_pre_authorization BOOLEAN       NOT NULL DEFAULT FALSE,
                final_status          TEXT,
                pipeline_trace        JSONB
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS claim_documents (
                id        SERIAL  PRIMARY KEY,
                claim_id  TEXT    NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                file_id   TEXT    NOT NULL,
                file_name TEXT    NOT NULL,
                mime_type TEXT    NOT NULL,
                file_data BYTEA   NOT NULL
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS claims_history (
                claim_id       TEXT PRIMARY KEY,
                member_id      TEXT          NOT NULL,
                claimed_amount NUMERIC(12,2) NOT NULL,
                treatment_date DATE          NOT NULL,
                is_approved    BOOLEAN       NOT NULL DEFAULT FALSE,
                created_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_claims_member ON claims(member_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_member ON claims_history(member_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_hist_date ON claims_history(treatment_date)")


async def insert_claim(
    claim_id: str, user_id: str, session_id: str,
    created_at: datetime, inp: dict[str, Any],
) -> None:
    assert _pool
    treatment_date = inp["treatment_date"]
    if isinstance(treatment_date, str):
        treatment_date = date.fromisoformat(treatment_date)

    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO claims
                (claim_id, user_id, session_id, created_at,
                 member_id, policy_id, claim_category, treatment_date,
                 claimed_amount, relationship_claim_type,
                 patient_member_id, has_pre_authorization)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            """,
            claim_id, user_id, session_id, created_at,
            inp["member_id"], inp["policy_id"],
            inp["claim_category"], treatment_date,
            inp["claimed_amount"], inp["relationship_claim_type"],
            inp.get("patient_member_id"), inp.get("has_pre_authorization", False),
        )


async def insert_document(
    claim_id: str, file_id: str, file_name: str, mime_type: str, file_data: bytes
) -> None:
    assert _pool
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO claim_documents (claim_id, file_id, file_name, mime_type, file_data) VALUES ($1,$2,$3,$4,$5)",
            claim_id, file_id, file_name, mime_type, file_data,
        )


async def get_claim_with_documents(claim_id: str) -> dict[str, Any] | None:
    assert _pool
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM claims WHERE claim_id=$1", claim_id)
        if not row:
            return None
        claim = dict(row)
        docs = await conn.fetch(
            "SELECT file_id, file_name, mime_type, file_data FROM claim_documents WHERE claim_id=$1 ORDER BY id",
            claim_id,
        )
        claim["documents"] = [
            {"file_id": d["file_id"], "file_name": d["file_name"],
             "mime_type": d["mime_type"], "bytes": bytes(d["file_data"])}
            for d in docs
        ]
        return claim


async def get_all_claims_for_staff() -> list[dict[str, Any]]:
    assert _pool
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM claims ORDER BY created_at DESC"
        )
        result = []
        for row in rows:
            c = dict(row)
            # Serialise date/datetime
            if isinstance(c.get("treatment_date"), date):
                c["treatment_date"] = c["treatment_date"].isoformat()
            if isinstance(c.get("created_at"), datetime):
                c["created_at"] = c["created_at"].isoformat()
            # pipeline_trace comes out as a dict from asyncpg JSONB, or None.
            # If it was stored as a JSON string, parse it here.
            pipeline_trace = c.get("pipeline_trace")
            if isinstance(pipeline_trace, str):
                try:
                    c["pipeline_trace"] = json.loads(pipeline_trace)
                except json.JSONDecodeError:
                    c["pipeline_trace"] = None
            docs = await conn.fetch(
                "SELECT file_id, file_name, mime_type FROM claim_documents WHERE claim_id=$1 ORDER BY id",
                c["claim_id"],
            )
            c["documents"] = [dict(d) for d in docs]
            c["input"] = {
                "member_id": c.pop("member_id"),
                "policy_id": c.pop("policy_id"),
                "claim_category": c.pop("claim_category"),
                "treatment_date": c.pop("treatment_date"),
                "claimed_amount": float(c.pop("claimed_amount")),
                "relationship_claim_type": c.pop("relationship_claim_type"),
                "patient_member_id": c.pop("patient_member_id"),
                "has_pre_authorization": c.pop("has_pre_authorization"),
            }
            result.append(c)
        return result


async def update_claim_final(
    claim_id: str, final_status: str | None, pipeline_trace: dict | None
) -> None:
    assert _pool
    if pipeline_trace is not None and not isinstance(pipeline_trace, str):
        pipeline_trace = json.dumps(pipeline_trace)

    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE claims SET final_status=$1, pipeline_trace=$2::jsonb WHERE claim_id=$3",
            final_status,
            pipeline_trace,
            claim_id,
        )


async def db_register_claim(
    claim_id: str, member_id: str, claimed_amount: float, treatment_date: str
) -> None:
    assert _pool
    if isinstance(treatment_date, str):
        treatment_date = date.fromisoformat(treatment_date)

    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO claims_history (claim_id, member_id, claimed_amount, treatment_date)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (claim_id) DO NOTHING
            """,
            claim_id, member_id, claimed_amount, treatment_date,
        )


async def db_mark_claim_approved(claim_id: str) -> None:
    assert _pool
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE claims_history SET is_approved=TRUE WHERE claim_id=$1", claim_id
        )
