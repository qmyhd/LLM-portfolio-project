"""Video Research API — resolve a YouTube URL to metadata + live transcript.

Quote CRUD lands in a later phase. Root-mounted router. Transcripts are fetched
live and never persisted (spec: saved excerpts only).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.db import execute_sql
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
