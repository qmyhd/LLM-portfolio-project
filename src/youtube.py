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
    "No working transcript provider/proxy is configured."
)

# TranscriptAPI.com (preferred provider when TRANSCRIPTAPI_KEY is set).
_TRANSCRIPTAPI_URL = "https://transcriptapi.com/api/v2/youtube/transcript"
_LAST_SEGMENT_DEFAULT_DURATION = 3.0

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


def _normalize_transcriptapi(data) -> list[dict]:
    """Normalize a TranscriptAPI.com payload into [{text, start, duration}].

    Tolerant of shape: a top-level list, or a dict holding the segment list under
    a common key. When a segment lacks a duration, derive it from the next
    segment's start (positive delta), defaulting the last segment to a small
    constant. Isolated so it can be unit-tested without the network.
    """
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = None
        for key in ("transcript", "segments", "data", "results"):
            value = data.get(key)
            if isinstance(value, list):
                items = value
                break
        if items is None:
            return []
    else:
        return []

    # Pass 1: extract text + start (+ duration if present).
    parsed: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        start = it.get("start", it.get("offset", it.get("start_time")))
        try:
            start_f = float(start)
        except (TypeError, ValueError):
            continue
        dur = it.get("duration", it.get("dur"))
        try:
            dur_f = float(dur) if dur is not None else None
        except (TypeError, ValueError):
            dur_f = None
        parsed.append({"text": str(it.get("text", "") or ""), "start": start_f, "duration": dur_f})

    # Pass 2: derive missing durations from the next start.
    out: list[dict] = []
    for i, seg in enumerate(parsed):
        dur = seg["duration"]
        if dur is None:
            if i + 1 < len(parsed) and parsed[i + 1]["start"] > seg["start"]:
                dur = parsed[i + 1]["start"] - seg["start"]
            else:
                dur = _LAST_SEGMENT_DEFAULT_DURATION
        out.append({"text": seg["text"], "start": seg["start"], "duration": float(dur)})
    return out


def _fetch_via_transcriptapi(video_id: str) -> list[dict] | None:
    """Fetch a transcript via TranscriptAPI.com. Returns normalized segments, or
    None to signal "fall back to youtube-transcript-api". Never raises; the API
    key is never logged.
    """
    api_key = os.getenv("TRANSCRIPTAPI_KEY")
    if not api_key:
        return None
    import requests
    try:
        r = requests.get(
            _TRANSCRIPTAPI_URL,
            params={"video_id": video_id},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if r.status_code != 200:
            logger.info("TranscriptAPI non-200 for %s: %s", video_id, r.status_code)
            return None
        segs = _normalize_transcriptapi(r.json())
        return segs or None
    except Exception:  # noqa: BLE001 — never raise; signal fallback
        logger.info("TranscriptAPI request failed for %s", video_id)
        return None


def fetch_transcript(video_id: str) -> tuple[bool, list[dict], str | None]:
    """(available, segments, reason). Never raises.

    Provider order: TranscriptAPI.com (if TRANSCRIPTAPI_KEY set) ->
    youtube-transcript-api (with optional Webshare/generic proxy) -> unavailable.
    """
    # 1. Preferred: TranscriptAPI.com (never raises; None -> fall back).
    if os.getenv("TRANSCRIPTAPI_KEY"):
        provider_segs = _fetch_via_transcriptapi(video_id)
        if provider_segs:
            return True, provider_segs, None

    # 2. Fallback: youtube-transcript-api (+ optional proxy).
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
