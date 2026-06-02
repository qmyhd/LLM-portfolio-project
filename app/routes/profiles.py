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
import os

from fastapi import APIRouter, HTTPException, Path, Query
from openai import OpenAI
from pydantic import BaseModel
from sqlalchemy import text

from app.track_record import compute_stock_track_record
from src.analysis.orchestrator import get_stock_analysis
from src.bucket import BucketQuery, validate_bucket
from src.db import execute_sql, transaction
from src.openbb_service import get_company_news

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


PROFILE_STALE_DAYS = int(os.getenv("PROFILE_STALE_DAYS", "90"))


@router.get("/profiles")
async def list_profiles(
    bucket: str | None = BucketQuery,
    queue: int = Query(0, description="1 = return the prioritized review queue"),
):
    b = validate_bucket(bucket)  # may be None ('all' view)
    bclause = " AND COALESCE(acc.bucket, 'other') = :bucket " if b else ""
    bparams = {"bucket": b} if b else {}

    if not queue:
        rows = execute_sql(
            """
            SELECT symbol, bucket, conviction, status, updated_at, reviewed_at
            FROM stock_thesis_profiles
            WHERE status != 'archived'
            ORDER BY updated_at DESC
            """,
            fetch_results=True,
        ) or []
        profiles = []
        for r in rows:
            rd = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
            rd["updated_at"] = str(rd.get("updated_at")) if rd.get("updated_at") else None
            rd["reviewed_at"] = str(rd.get("reviewed_at")) if rd.get("reviewed_at") else None
            profiles.append(rd)
        return {"profiles": profiles}

    # Queue: held (symbol, bucket) pairs LEFT JOIN profiles, prioritized.
    rows = execute_sql(
        f"""
        WITH held AS (
            SELECT UPPER(p.symbol) AS symbol, COALESCE(acc.bucket, 'other') AS bucket
            FROM positions p
            LEFT JOIN accounts acc ON acc.id = p.account_id
            WHERE p.quantity > 0
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
              {bclause}
            GROUP BY UPPER(p.symbol), COALESCE(acc.bucket, 'other')
        )
        SELECT h.symbol, h.bucket,
               (tp.id IS NOT NULL) AS has_profile,
               tp.reviewed_at,
               (tp.reviewed_at IS NOT NULL
                  AND tp.reviewed_at < NOW() - (:stale_days || ' days')::interval) AS stale,
               EXISTS (
                   SELECT 1 FROM activities a
                   LEFT JOIN accounts acc2 ON acc2.id = a.account_id
                   WHERE UPPER(a.symbol) = h.symbol
                     AND COALESCE(acc2.bucket, 'other') = h.bucket
                     AND (tp.reviewed_at IS NULL OR a.trade_date > tp.reviewed_at)
               ) AS changed
        FROM held h
        LEFT JOIN stock_thesis_profiles tp
          ON UPPER(tp.symbol) = h.symbol AND tp.bucket = h.bucket
          AND tp.status != 'archived'
        """,
        params={"stale_days": PROFILE_STALE_DAYS, **bparams},
        fetch_results=True,
    ) or []

    def _reason(rd: dict) -> str:
        if not rd.get("has_profile"):
            return "no_profile"
        if rd.get("stale"):
            return "stale"
        if rd.get("changed"):
            return "changed"
        return "ok"

    _rank = {"no_profile": 0, "stale": 1, "changed": 2, "ok": 3}
    items = []
    for r in rows:
        rd = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
        items.append({"symbol": rd["symbol"], "bucket": rd["bucket"],
                      "hasProfile": bool(rd.get("has_profile")), "reason": _reason(rd)})
    items.sort(key=lambda it: _rank[it["reason"]])
    return {"queue": items}


def _ideas_digest(symbol: str) -> list[dict]:
    rows = execute_sql(
        """
        SELECT dpi.direction, dpi.labels, dpi.idea_text, dm.created_at, dm.author
        FROM discord_parsed_ideas dpi
        LEFT JOIN discord_messages dm ON dpi.message_id::text = dm.message_id
        WHERE UPPER(dpi.primary_symbol) = :symbol
        ORDER BY dm.created_at DESC NULLS LAST
        LIMIT 10
        """,
        params={"symbol": symbol.upper()},
        fetch_results=True,
    ) or []
    out = []
    for r in rows:
        rd = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
        out.append({
            "direction": rd.get("direction"),
            "labels": list(rd.get("labels") or []),
            "text": (rd.get("idea_text") or "")[:200],
            "author": rd.get("author"),
        })
    return out


@router.post("/stocks/{ticker}/profile/autofill")
async def autofill_profile(
    ticker: str = Path(...),
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    symbol = ticker.upper()
    sources: list[str] = []

    try:
        track_record = compute_stock_track_record(symbol, b)
        sources.append("trades")
    except Exception as e:  # noqa: BLE001
        logger.warning("autofill track record failed for %s: %s", symbol, e)
        track_record = None

    catalysts: list[dict] = []
    try:
        news = get_company_news(symbol, limit=8) or []
        catalysts = [{"title": n.get("title"), "date": n.get("date"),
                      "source": n.get("source"), "url": n.get("url")} for n in news]
        if catalysts:
            sources.append("news")
    except Exception as e:  # noqa: BLE001
        logger.warning("autofill news failed for %s: %s", symbol, e)

    consensus: dict | None = None
    try:
        # refresh=False tolerates stale; cold cache runs the full pipeline.
        consensus = await get_stock_analysis(symbol, refresh=False, bucket=b)
        sources.append("analysis")
    except Exception as e:  # noqa: BLE001
        logger.warning("autofill analysis failed for %s: %s", symbol, e)

    ideas = _ideas_digest(symbol)
    if ideas:
        sources.append("ideas")

    return {
        "symbol": symbol, "bucket": b,
        "trackRecord": track_record,
        "catalysts": catalysts,
        "consensus": consensus,
        "ideas": ideas,
        "dataSources": sources,
    }


_PROFILE_MODEL_LIGHT = os.getenv("OPENAI_MODEL_PROFILE_LIGHT", "gpt-5-mini")
_PROFILE_MODEL_SYNTH = os.getenv("OPENAI_MODEL_PROFILE_SYNTH", "gpt-5-mini")


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def _chat_json(model: str, system: str, user: str, max_tokens: int = 700) -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens, temperature=0.3,
    )
    return json.loads(_strip_fences(completion.choices[0].message.content or "{}"))


class InterviewBody(BaseModel):
    autofill: dict = {}
    answers: list[dict] = []  # [{field, question, answer}]


@router.post("/stocks/{ticker}/profile/interview")
async def interview(
    ticker: str = Path(...),
    body: InterviewBody = ...,  # noqa: B008
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    symbol = ticker.upper()
    follow_up = bool(body.answers)

    if not follow_up:
        system = (
            "You interview an investor to capture the SUBJECTIVE parts of their thesis for a "
            "stock. Given factual data, produce 3-5 targeted questions. Return ONLY JSON: "
            '{"questions":[{"field": "thesis|sell_trigger|conviction|catalyst|risk", '
            '"question": "..."}]}. No markdown.'
        )
        user = f"SYMBOL: {symbol} ({b})\nDATA:\n{json.dumps(body.autofill)[:3000]}"
    else:
        system = (
            "You already asked questions and received answers. Inspect them against the data. "
            "If an answer is thin or CONTRADICTS the track record (e.g. bullish thesis but the "
            "trades show repeated selling), return 1-2 targeted follow-up questions; otherwise "
            'return an empty list. Return ONLY JSON: {"questions":[{"field":"...","question":"..."}]}.'
        )
        user = (
            f"SYMBOL: {symbol} ({b})\nDATA:\n{json.dumps(body.autofill)[:2000]}\n\n"
            f"ANSWERS:\n{json.dumps(body.answers)[:2000]}"
        )

    try:
        result = _chat_json(_PROFILE_MODEL_LIGHT, system, user, max_tokens=600)
        questions = result.get("questions", [])
    except json.JSONDecodeError:
        questions = []
    except Exception as e:  # noqa: BLE001
        logger.error("interview failed for %s: %s", symbol, e)
        raise HTTPException(status_code=502, detail="AI interview failed") from None

    return {"symbol": symbol, "bucket": b, "questions": questions, "followUp": follow_up}
