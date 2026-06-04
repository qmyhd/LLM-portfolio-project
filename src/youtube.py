"""YouTube helpers: URL/channel parsing + fail-safe transcript/oEmbed fetch.

Pure parsers have no network. Network fetchers NEVER raise — they return a
sentinel so the API can degrade gracefully (spec section 5).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(url: str | None) -> str | None:
    """Extract an 11-char YouTube video id from common URL forms, else None."""
    if not url:
        return None
    try:
        u = urlparse(url.strip())
    except (ValueError, AttributeError):
        return None
    host = (u.netloc or "").lower().removeprefix("www.")
    if host == "youtu.be":
        cand = u.path.lstrip("/").split("/")[0]
        return cand if _VIDEO_ID_RE.match(cand) else None
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if u.path == "/watch":
            cand = (parse_qs(u.query).get("v") or [""])[0]
            return cand if _VIDEO_ID_RE.match(cand) else None
        for prefix in ("/shorts/", "/embed/", "/live/", "/v/"):
            if u.path.startswith(prefix):
                cand = u.path[len(prefix):].split("/")[0]
                return cand if _VIDEO_ID_RE.match(cand) else None
    return None


def parse_channel_key(author_url: str | None) -> str | None:
    """Stable channel key from an oEmbed author_url.

    Prefers a /channel/UC... id; falls back to an @handle (best-effort, V1);
    returns None when neither is derivable (caller then skips identity upsert).
    """
    if not author_url:
        return None
    try:
        path = urlparse(author_url).path or ""
    except (ValueError, AttributeError):
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    if parts[0] == "channel" and len(parts) > 1 and parts[1].startswith("UC"):
        return parts[1]
    if parts[0].startswith("@"):
        return parts[0]
    return None


def _get_transcript_raw(video_id: str) -> list[dict]:
    """Thin call to youtube-transcript-api, isolated for mocking + version adaptation.

    Returns a list of {text, start, duration}. If the installed library version
    exposes a different surface than the call below, adapt ONLY this function
    (keep the return shape) — the spike in Step 5 confirms the actual surface.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    # youtube-transcript-api >=1.0 replaced the static get_transcript(...) with an
    # instance API: YouTubeTranscriptApi().fetch(video_id) -> FetchedTranscript,
    # which exposes .to_raw_data() yielding {text, start, duration} dicts.
    fetched = YouTubeTranscriptApi().fetch(video_id, languages=["en", "en-US"])
    return fetched.to_raw_data()


def fetch_transcript(video_id: str) -> tuple[bool, list[dict], str | None]:
    """(available, segments, reason). Never raises."""
    try:
        raw = _get_transcript_raw(video_id) or []
        segs = [
            {"text": s.get("text", ""), "start": float(s.get("start", 0.0)),
             "duration": float(s.get("duration", 0.0))}
            for s in raw
        ]
        if not segs:
            return False, [], "empty transcript"
        return True, segs, None
    except Exception as e:  # noqa: BLE001 — degrade, never raise
        logger.info("transcript unavailable for %s: %s", video_id, e.__class__.__name__)
        return False, [], e.__class__.__name__


def fetch_oembed(url: str) -> dict:
    """YouTube oEmbed metadata (title/author). Never raises — {} on failure."""
    import requests
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"}, timeout=8,
        )
        if r.status_code != 200:
            return {}
        d = r.json()
        return {"title": d.get("title"), "author_name": d.get("author_name"),
                "author_url": d.get("author_url")}
    except Exception:  # noqa: BLE001
        return {}
