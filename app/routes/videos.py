"""Video Research API — resolve a YouTube URL to metadata + live transcript.

Quote CRUD lands in a later phase. Root-mounted router. Transcripts are fetched
live and never persisted (spec: saved excerpts only).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import text

from src.db import execute_sql, transaction
from src.youtube import fetch_oembed, fetch_transcript, parse_channel_key, parse_video_id

logger = logging.getLogger(__name__)
router = APIRouter()


class ResolveBody(BaseModel):
    url: str


@router.post("/videos/resolve")
async def resolve_video(body: ResolveBody):
    vid = parse_video_id(body.url)
    if not vid:
        raise HTTPException(status_code=400, detail="Unparseable YouTube URL")

    meta = fetch_oembed(body.url)  # {} on failure, never raises
    channel_name = meta.get("author_name")
    channel_url = meta.get("author_url")

    available, segments, reason = fetch_transcript(vid)  # never raises

    suggested_person_id = None
    suggested_person_name = None
    key = parse_channel_key(channel_url)
    if key:
        try:
            rows = execute_sql(
                "SELECT si.person_id, p.full_name "
                "FROM source_identities si JOIN people p ON p.id = si.person_id "
                "WHERE si.platform = 'youtube' AND si.platform_user_id = :key "
                "AND si.match_status = 'confirmed'",
                params={"key": key},
                fetch_results=True,
            ) or []
            if rows:
                m = rows[0]._mapping if hasattr(rows[0], "_mapping") else rows[0]
                suggested_person_id = m["person_id"]
                suggested_person_name = m["full_name"]
            else:
                # Surface the channel in the unmatched review queue. ON CONFLICT
                # DO NOTHING never overwrites a confirmed/conflict row; we never
                # auto-create a Person.
                execute_sql(
                    "INSERT INTO source_identities (platform, platform_user_id, handle, match_status) "
                    "VALUES ('youtube', :key, :handle, 'suggested') "
                    "ON CONFLICT (platform, platform_user_id) DO NOTHING",
                    params={"key": key, "handle": channel_name},
                )
        except Exception:  # noqa: BLE001 — speaker resolution must never 500 the resolve
            logger.warning("speaker resolution failed for channel %s", key, exc_info=True)
            suggested_person_id = None
            suggested_person_name = None

    return {
        "videoId": vid,
        "url": body.url,
        "title": meta.get("title"),
        "channelName": channel_name,
        "channelUrl": channel_url,
        "transcriptAvailable": available,
        "reason": reason,
        "segments": segments,
        "suggestedPersonId": suggested_person_id,
        "suggestedPersonName": suggested_person_name,
    }


class QuoteBody(BaseModel):
    videoId: str
    videoUrl: str
    videoTitle: str | None = None
    channelName: str | None = None
    channelUrl: str | None = None
    quoteText: str
    startSeconds: float
    endSeconds: float | None = None
    personId: int | None = None
    categorySlug: str | None = None
    ticker: str | None = None
    stockThesisProfileId: int | None = None
    thesisNote: str | None = None
    tags: list[str] = []
    notes: str | None = None


_QUOTE_SELECT = """
    SELECT vq.id, vq.video_id, vq.video_url, vq.video_title, vq.channel_name,
           vq.channel_url, vq.quote_text, vq.start_seconds, vq.end_seconds,
           vq.person_id, vq.category_slug, vq.ticker, vq.stock_thesis_profile_id,
           vq.thesis_note, vq.tags, vq.notes, vq.status, vq.saved_at, vq.updated_at,
           p.full_name AS person_name, c.label AS category_label
    FROM video_quotes vq
    LEFT JOIN people p ON p.id = vq.person_id
    LEFT JOIN credibility_categories c ON c.slug = vq.category_slug
"""


def _quote_out(row) -> dict:
    m = row._mapping if hasattr(row, "_mapping") else row
    def _num(v):
        return float(v) if v is not None else None
    return {
        "id": m["id"], "videoId": m["video_id"], "videoUrl": m["video_url"],
        "videoTitle": m.get("video_title"), "channelName": m.get("channel_name"),
        "channelUrl": m.get("channel_url"), "quoteText": m["quote_text"],
        "startSeconds": _num(m.get("start_seconds")), "endSeconds": _num(m.get("end_seconds")),
        "personId": m.get("person_id"), "personName": m.get("person_name"),
        "categorySlug": m.get("category_slug"), "categoryLabel": m.get("category_label"),
        "ticker": m.get("ticker"), "stockThesisProfileId": m.get("stock_thesis_profile_id"),
        "thesisNote": m.get("thesis_note"), "tags": list(m.get("tags") or []),
        "notes": m.get("notes"), "status": m.get("status"),
        "savedAt": str(m["saved_at"]) if m.get("saved_at") else None,
        "updatedAt": str(m["updated_at"]) if m.get("updated_at") else None,
    }


def _quote_params(body: QuoteBody) -> dict:
    return {
        "video_id": body.videoId, "video_url": body.videoUrl, "video_title": body.videoTitle,
        "channel_name": body.channelName, "channel_url": body.channelUrl,
        "quote_text": body.quoteText, "start_seconds": body.startSeconds,
        "end_seconds": body.endSeconds, "person_id": body.personId,
        "category_slug": body.categorySlug, "ticker": body.ticker,
        "stock_thesis_profile_id": body.stockThesisProfileId, "thesis_note": body.thesisNote,
        "tags": body.tags or [], "notes": body.notes,
    }


@router.post("/quotes")
async def create_quote(body: QuoteBody):
    params = _quote_params(body)
    with transaction() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO video_quotes
                    (video_id, video_url, video_title, channel_name, channel_url,
                     quote_text, start_seconds, end_seconds, person_id, category_slug,
                     ticker, stock_thesis_profile_id, thesis_note, tags, notes)
                VALUES
                    (:video_id, :video_url, :video_title, :channel_name, :channel_url,
                     :quote_text, :start_seconds, :end_seconds, :person_id, :category_slug,
                     :ticker, :stock_thesis_profile_id, :thesis_note, :tags, :notes)
                RETURNING id
                """
            ),
            params,
        )
        new_id = row.fetchone()[0]
    return {
        "id": new_id, "videoId": body.videoId, "videoUrl": body.videoUrl,
        "videoTitle": body.videoTitle, "channelName": body.channelName,
        "channelUrl": body.channelUrl, "quoteText": body.quoteText,
        "startSeconds": body.startSeconds, "endSeconds": body.endSeconds,
        "personId": body.personId, "personName": None,
        "categorySlug": body.categorySlug, "categoryLabel": None,
        "ticker": body.ticker, "stockThesisProfileId": body.stockThesisProfileId,
        "thesisNote": body.thesisNote, "tags": body.tags or [], "notes": body.notes,
        "status": "active",
    }


@router.get("/quotes")
async def list_quotes(
    q: str | None = Query(None),
    person_id: int | None = Query(None),
    category: str | None = Query(None),
    ticker: str | None = Query(None),
    video_id: str | None = Query(None),
    status: str = Query("active"),
):
    where = ["vq.status = :status"]
    params: dict = {"status": status}
    if q:
        where.append("vq.quote_text ILIKE :q")
        params["q"] = f"%{q}%"
    if person_id is not None:
        where.append("vq.person_id = :person_id")
        params["person_id"] = person_id
    if category:
        where.append("vq.category_slug = :category")
        params["category"] = category
    if ticker:
        where.append("UPPER(vq.ticker) = UPPER(:ticker)")
        params["ticker"] = ticker
    if video_id:
        where.append("vq.video_id = :video_id")
        params["video_id"] = video_id
    rows = execute_sql(
        _QUOTE_SELECT + " WHERE " + " AND ".join(where) + " ORDER BY vq.saved_at DESC LIMIT 500",
        params=params,
        fetch_results=True,
    ) or []
    return {"quotes": [_quote_out(r) for r in rows]}


@router.get("/quotes/{id}")
async def get_quote(id: int = Path(...)):
    rows = execute_sql(_QUOTE_SELECT + " WHERE vq.id = :id", params={"id": id}, fetch_results=True) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Quote not found")
    return _quote_out(rows[0])


@router.put("/quotes/{id}")
async def update_quote(id: int = Path(...), body: QuoteBody = ...):  # noqa: B008
    params = {**_quote_params(body), "id": id}
    with transaction() as conn:
        row = conn.execute(
            text(
                """
                UPDATE video_quotes SET
                    video_id = :video_id, video_url = :video_url, video_title = :video_title,
                    channel_name = :channel_name, channel_url = :channel_url,
                    quote_text = :quote_text, start_seconds = :start_seconds,
                    end_seconds = :end_seconds, person_id = :person_id,
                    category_slug = :category_slug, ticker = :ticker,
                    stock_thesis_profile_id = :stock_thesis_profile_id,
                    thesis_note = :thesis_note, tags = :tags, notes = :notes,
                    updated_at = NOW()
                WHERE id = :id
                RETURNING id
                """
            ),
            params,
        )
        if row.fetchone() is None:
            raise HTTPException(status_code=404, detail="Quote not found")
    return {
        "id": id,
        "videoId": body.videoId, "videoUrl": body.videoUrl, "quoteText": body.quoteText,
        "startSeconds": body.startSeconds, "endSeconds": body.endSeconds,
        "personId": body.personId, "categorySlug": body.categorySlug, "ticker": body.ticker,
        "stockThesisProfileId": body.stockThesisProfileId, "thesisNote": body.thesisNote,
        "tags": body.tags or [], "notes": body.notes,
    }


@router.delete("/quotes/{id}")
async def delete_quote(id: int = Path(...)):
    rows = execute_sql(
        "UPDATE video_quotes SET status='archived', updated_at=NOW() WHERE id = :id RETURNING id",
        params={"id": id},
        fetch_results=True,
    ) or []
    if not rows:
        raise HTTPException(status_code=404, detail="Quote not found")
    return {"status": "archived", "id": id}
