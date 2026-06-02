"""Stock thesis profile API (AI-co-authored per-(symbol, bucket) dossiers).

Root-mounted router. Endpoints:
- GET    /stocks/{ticker}/profile            fetch a profile (+ track record)
- PUT    /stocks/{ticker}/profile            save/update (append revision)
- DELETE /stocks/{ticker}/profile            archive
- GET    /stocks/{ticker}/profile/revisions  saved-snapshot history
- GET    /profiles                           list / prioritized queue
- POST   /stocks/{ticker}/profile/autofill   assemble data sections
- POST   /stocks/{ticker}/profile/interview  tailored questions (+ follow-ups)
- POST   /stocks/{ticker}/profile/synthesize merge answers+data -> draft thesis
"""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import text

from app.track_record import compute_stock_track_record
from src.bucket import BucketQuery, validate_bucket
from src.db import execute_sql, transaction

logger = logging.getLogger(__name__)
router = APIRouter()


def _lock_key(symbol: str, bucket: str) -> int:
    digest = hashlib.sha256(f"{symbol}:{bucket}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _require_concrete_bucket(bucket: str | None) -> str:
    b = validate_bucket(bucket)
    if not b:
        raise HTTPException(
            status_code=400,
            detail="A concrete bucket is required to write a profile (not 'all').",
        )
    return b


class ProfileBody(BaseModel):
    thesis: str | None = None
    conviction: int | None = None
    convictionRationale: str | None = None
    bullCase: str | None = None
    bearCase: str | None = None
    catalysts: list[dict] = []
    risks: list[dict] = []
    levels: dict = {}
    horizon: str | None = None
    tags: list[str] = []
    status: str = "active"
    aiAutofillJson: dict | None = None
    interviewJson: dict | None = None
    modelUsed: str | None = None
    dataSources: list[str] = []


class ThesisProfile(BaseModel):
    symbol: str
    bucket: str
    thesis: str | None = None
    conviction: int | None = None
    convictionRationale: str | None = None
    bullCase: str | None = None
    bearCase: str | None = None
    catalysts: list[dict] = []
    risks: list[dict] = []
    levels: dict = {}
    horizon: str | None = None
    tags: list[str] = []
    status: str = "draft"
    updatedAt: str | None = None
    reviewedAt: str | None = None
    trackRecord: dict | None = None


def _row_to_profile(rd: dict, track_record: dict | None) -> ThesisProfile:
    return ThesisProfile(
        symbol=rd["symbol"], bucket=rd["bucket"], thesis=rd.get("thesis"),
        conviction=rd.get("conviction"), convictionRationale=rd.get("conviction_rationale"),
        bullCase=rd.get("bull_case"), bearCase=rd.get("bear_case"),
        catalysts=rd.get("catalysts") or [], risks=rd.get("risks") or [],
        levels=rd.get("levels") or {}, horizon=rd.get("horizon"),
        tags=list(rd.get("tags") or []), status=rd.get("status") or "draft",
        updatedAt=str(rd["updated_at"]) if rd.get("updated_at") else None,
        reviewedAt=str(rd["reviewed_at"]) if rd.get("reviewed_at") else None,
        trackRecord=track_record,
    )


def _fetch_profile_row(symbol: str, bucket: str) -> dict | None:
    rows = execute_sql(
        """
        SELECT symbol, bucket, thesis, conviction, conviction_rationale, bull_case,
               bear_case, catalysts, risks, levels, horizon, tags, status,
               updated_at, reviewed_at
        FROM stock_thesis_profiles
        WHERE UPPER(symbol) = :symbol AND bucket = :bucket
        """,
        params={"symbol": symbol.upper(), "bucket": bucket},
        fetch_results=True,
    ) or []
    if not rows:
        return None
    return dict(rows[0]._mapping) if hasattr(rows[0], "_mapping") else dict(rows[0])


@router.get("/stocks/{ticker}/profile", response_model=ThesisProfile)
async def get_profile(
    ticker: str = Path(...),
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    rd = _fetch_profile_row(ticker, b)
    if rd is None:
        raise HTTPException(status_code=404, detail="No profile for this (symbol, bucket)")
    tr = compute_stock_track_record(ticker, b)
    return _row_to_profile(rd, tr)


@router.put("/stocks/{ticker}/profile", response_model=ThesisProfile)
async def put_profile(
    ticker: str = Path(...),
    body: ProfileBody = ...,  # noqa: B008
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    symbol = ticker.upper()
    lock = _lock_key(symbol, b)
    params = {
        "symbol": symbol, "bucket": b, "thesis": body.thesis,
        "conviction": body.conviction, "conviction_rationale": body.convictionRationale,
        "bull_case": body.bullCase, "bear_case": body.bearCase,
        "catalysts": json.dumps(body.catalysts), "risks": json.dumps(body.risks),
        "levels": json.dumps(body.levels), "horizon": body.horizon,
        "tags": body.tags or [], "status": body.status,
        "ai_autofill_json": json.dumps(body.aiAutofillJson) if body.aiAutofillJson else None,
        "interview_json": json.dumps(body.interviewJson) if body.interviewJson else None,
        "model_used": body.modelUsed, "data_sources": body.dataSources or [],
    }
    with transaction() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock})
        row = conn.execute(
            text(
                """
                INSERT INTO stock_thesis_profiles
                    (symbol, bucket, thesis, conviction, conviction_rationale, bull_case,
                     bear_case, catalysts, risks, levels, horizon, tags, status,
                     ai_autofill_json, interview_json, model_used, data_sources, reviewed_at)
                VALUES
                    (:symbol, :bucket, :thesis, :conviction, :conviction_rationale, :bull_case,
                     :bear_case, CAST(:catalysts AS jsonb), CAST(:risks AS jsonb),
                     CAST(:levels AS jsonb), :horizon, :tags, :status,
                     CAST(:ai_autofill_json AS jsonb), CAST(:interview_json AS jsonb),
                     :model_used, :data_sources, NOW())
                ON CONFLICT (symbol, bucket) DO UPDATE SET
                    thesis = EXCLUDED.thesis, conviction = EXCLUDED.conviction,
                    conviction_rationale = EXCLUDED.conviction_rationale,
                    bull_case = EXCLUDED.bull_case, bear_case = EXCLUDED.bear_case,
                    catalysts = EXCLUDED.catalysts, risks = EXCLUDED.risks,
                    levels = EXCLUDED.levels, horizon = EXCLUDED.horizon,
                    tags = EXCLUDED.tags, status = EXCLUDED.status,
                    ai_autofill_json = EXCLUDED.ai_autofill_json,
                    interview_json = EXCLUDED.interview_json,
                    model_used = EXCLUDED.model_used, data_sources = EXCLUDED.data_sources,
                    reviewed_at = NOW()
                RETURNING id
                """
            ),
            params,
        )
        profile_id = row.fetchone()[0]
        conn.execute(
            text(
                """
                INSERT INTO stock_thesis_profile_revisions
                    (profile_id, symbol, bucket, snapshot_json, conviction)
                VALUES (:pid, :symbol, :bucket, CAST(:snap AS jsonb), :conviction)
                """
            ),
            {"pid": profile_id, "symbol": symbol, "bucket": b,
             "snap": body.model_dump_json(), "conviction": body.conviction},
        )
    rd = _fetch_profile_row(symbol, b)
    return _row_to_profile(rd or {}, None)


@router.delete("/stocks/{ticker}/profile")
async def delete_profile(
    ticker: str = Path(...),
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    execute_sql(
        "UPDATE stock_thesis_profiles SET status = 'archived' "
        "WHERE UPPER(symbol) = :symbol AND bucket = :bucket",
        params={"symbol": ticker.upper(), "bucket": b},
    )
    return {"status": "archived", "symbol": ticker.upper(), "bucket": b}


@router.get("/stocks/{ticker}/profile/revisions")
async def get_revisions(
    ticker: str = Path(...),
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    rows = execute_sql(
        """
        SELECT r.snapshot_json, r.conviction, r.created_at
        FROM stock_thesis_profile_revisions r
        WHERE UPPER(r.symbol) = :symbol AND r.bucket = :bucket
        ORDER BY r.created_at DESC LIMIT 100
        """,
        params={"symbol": ticker.upper(), "bucket": b},
        fetch_results=True,
    ) or []
    out = []
    for row in rows:
        rd = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        out.append({
            "snapshot": rd.get("snapshot_json"),
            "conviction": rd.get("conviction"),
            "createdAt": str(rd["created_at"]) if rd.get("created_at") else None,
        })
    return {"symbol": ticker.upper(), "bucket": b, "revisions": out}
