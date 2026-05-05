"""
PostgreSQL-backed claims history store (psycopg2, sync).

Called synchronously by the policy decision agent tools.
main.py uses the async counterparts in db.py.
"""
from __future__ import annotations

import os
from datetime import date

import psycopg2
import psycopg2.pool

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, os.getenv("DATABASE_URL"))
    return _pool


def _exec(query: str, params: tuple = (), fetch: str | None = None):
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()
            if fetch == "one":
                return cur.fetchone()
            if fetch == "all":
                return cur.fetchall()
    finally:
        pool.putconn(conn)


def register_claim(
    claim_id: str, member_id: str, claimed_amount: float, treatment_date: str
) -> None:
    _exec(
        """
        INSERT INTO claims_history (claim_id, member_id, claimed_amount, treatment_date)
        VALUES (%s, %s, %s, %s::date)
        ON CONFLICT (claim_id) DO NOTHING
        """,
        (claim_id, member_id, float(claimed_amount), treatment_date),
    )


def mark_claim_approved(claim_id: str) -> None:
    _exec(
        "UPDATE claims_history SET is_approved=TRUE WHERE claim_id=%s",
        (claim_id,),
    )


def get_ytd_claims_amount(member_id: str) -> float:
    current_year = date.today().year
    row = _exec(
        """
        SELECT COALESCE(SUM(claimed_amount), 0)
        FROM claims_history
        WHERE member_id=%s AND is_approved=TRUE
          AND EXTRACT(YEAR FROM treatment_date)=%s
        """,
        (member_id, current_year),
        fetch="one",
    )
    return float(row[0]) if row else 0.0


def get_same_day_claims_count(member_id: str, treatment_date: str) -> int:
    row = _exec(
        """
        SELECT COUNT(*) FROM claims_history
        WHERE member_id=%s AND treatment_date=%s::date
        """,
        (member_id, treatment_date),
        fetch="one",
    )
    return int(row[0]) if row else 0


def get_monthly_claims_count(member_id: str, year: int, month: int) -> int:
    row = _exec(
        """
        SELECT COUNT(*) FROM claims_history
        WHERE member_id=%s
          AND EXTRACT(YEAR FROM treatment_date)=%s
          AND EXTRACT(MONTH FROM treatment_date)=%s
        """,
        (member_id, year, month),
        fetch="one",
    )
    return int(row[0]) if row else 0


def get_family_ytd_claims_amount(member_ids: list[str]) -> float:
    """Sum YTD approved claims for all member IDs in a family."""
    if not member_ids:
        return 0.0
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            placeholders = ",".join("%s" for _ in member_ids)
            cur.execute(
                f"""
                SELECT COALESCE(SUM(claimed_amount), 0)
                FROM claims_history
                WHERE member_id IN ({placeholders}) AND is_approved=TRUE
                  AND EXTRACT(YEAR FROM treatment_date)=%s
                """,
                (*member_ids, date.today().year),
            )
            conn.commit()
            row = cur.fetchone()
            return float(row[0]) if row else 0.0
    finally:
        pool.putconn(conn)
