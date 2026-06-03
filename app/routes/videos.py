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
