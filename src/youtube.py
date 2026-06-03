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
