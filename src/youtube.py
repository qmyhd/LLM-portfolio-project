"""YouTube helpers: URL/channel parsing + fail-safe transcript/oEmbed fetch.

Pure parsers have no network. Network fetchers NEVER raise — they return a
sentinel so the API can degrade gracefully (spec section 5).
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# Exception class names (matched by name, not import — robust across library
# versions) that mean YouTube blocked this server's IP / request.
_BLOCKED_EXC_NAMES = frozenset({"RequestBlocked", "IpBlocked"})
_BLOCKED_REASON = (
    "YouTube blocked transcript requests from this server. "
    "Transcript proxy not configured or blocked."
)

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


def _build_proxy_config():
    """Optional proxy config for youtube-transcript-api, from environment.

    YouTube blocks transcript requests from many datacenter IPs (EC2), surfacing
    as RequestBlocked/IpBlocked. Routing through a residential/rotating proxy
    avoids that. Precedence: Webshare creds > generic HTTP(S) proxy > none.
    Credentials are NEVER logged. Returns a proxy config object or None.
    """
    ws_user = os.getenv("YOUTUBE_TRANSCRIPT_WEBSHARE_USERNAME")
    ws_pass = os.getenv("YOUTUBE_TRANSCRIPT_WEBSHARE_PASSWORD")
    if ws_user and ws_pass:
        from youtube_transcript_api.proxies import WebshareProxyConfig

        kwargs: dict = {"proxy_username": ws_user, "proxy_password": ws_pass}
        locations = os.getenv("YOUTUBE_TRANSCRIPT_WEBSHARE_LOCATIONS")
        if locations:
            parsed = [c.strip().lower() for c in locations.split(",") if c.strip()]
            if parsed:
                kwargs["filter_ip_locations"] = parsed
        return WebshareProxyConfig(**kwargs)

    http_proxy = os.getenv("YOUTUBE_TRANSCRIPT_HTTP_PROXY")
    https_proxy = os.getenv("YOUTUBE_TRANSCRIPT_HTTPS_PROXY")
    if http_proxy or https_proxy:
        from youtube_transcript_api.proxies import GenericProxyConfig

        return GenericProxyConfig(http_url=http_proxy, https_url=https_proxy)

    return None


def _get_transcript_raw(video_id: str) -> list[dict]:
    """Thin call to youtube-transcript-api, isolated for mocking + version adaptation.

    Returns a list of {text, start, duration}. youtube-transcript-api >=1.0 uses
    an instance API: YouTubeTranscriptApi(proxy_config=...).fetch(video_id) ->
    FetchedTranscript, which exposes .to_raw_data(). The optional proxy config
    routes around datacenter-IP blocking (see _build_proxy_config).
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi(proxy_config=_build_proxy_config())
    return api.fetch(video_id, languages=["en", "en-US"]).to_raw_data()


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
        name = e.__class__.__name__
        logger.info("transcript unavailable for %s: %s", video_id, name)
        if name in _BLOCKED_EXC_NAMES:
            return False, [], _BLOCKED_REASON
        return False, [], name


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
