"""Discord alerts for the owner: a sign-in waiting for approval, and a locked account.

Posts through the Discord REST API with the bot token already in the environment
(not through the running bot). Every function here returns a bool and never raises,
so an alert can never break sign-in. At most MAX_ALERTS_PER_DAY alerts (both kinds
together) are sent per New York calendar day; the counter is in-process.
"""

import logging
import os
import re
import threading
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

MAX_ALERTS_PER_DAY = 20

_API = "https://discord.com/api/v10/channels/{channel}/messages"
_DEFAULT_FRONTEND = "https://llmportfolio.app"
_TIMEOUT_SECONDS = 5
_MAX_FIELD = 100
_ZWSP = "\u200b"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029\s]+")
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")
_TOKEN = re.compile(r"://|\]\(|.", re.DOTALL)
_REPLACE = {"`": "'", "@": "@" + _ZWSP, "://": ":/" + _ZWSP + "/", "](": "] ("}
_BAD_URL = re.compile(r"\s|[\x00-\x1f\x7f]|\]\(|`")

_lock = threading.Lock()
_count_day: date | None = None
_count = 0
_cap_logged_for: date | None = None
_warned: set[str] = set()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    """The current date in America/New_York; UTC when tz data is unavailable."""
    now = _now_utc()
    try:
        return now.astimezone(ZoneInfo("America/New_York")).date()
    except Exception:
        return now.date()


def _reset_counter() -> None:
    global _count_day, _count, _cap_logged_for
    with _lock:
        _count_day, _count, _cap_logged_for = None, 0, None
        _warned.clear()


def cap_reached() -> bool:
    """Cheap check so callers can skip starting a thread; _take_slot stays the authority."""
    today = _today()
    with _lock:
        return _count_day == today and _count >= MAX_ALERTS_PER_DAY


def _warn_once(variable: str, problem: str) -> None:
    with _lock:
        if variable in _warned:
            return
        _warned.add(variable)
    logger.warning("Approval alerts disabled: %s is %s", variable, problem)


def _counter_state() -> tuple[date | None, int]:
    with _lock:
        return _count_day, _count


def _take_slot() -> bool:
    """Reserve one of today's alerts; False (one warning a day) once the cap is hit."""
    global _count_day, _count, _cap_logged_for
    today = _today()
    with _lock:
        if _count_day != today:
            _count_day, _count = today, 0
        if _count >= MAX_ALERTS_PER_DAY:
            if _cap_logged_for != today:
                _cap_logged_for = today
                logger.warning("Daily alert limit reached (%d attempts); no more alerts today", MAX_ALERTS_PER_DAY)
            return False
        _count += 1
        return True


def _flatten(value: str | None) -> str:
    """Drop invisible and direction-control characters, collapse whitespace to single spaces."""
    text = _INVISIBLE.sub("", str(value or ""))
    return _CONTROL.sub(" ", text).strip()


def _clean(value: str | None, *, lead: bool = False) -> str:
    """Make a stranger-supplied value safe for one line of a Discord message.

    The finished field is at most 100 characters; a replacement is never cut in half.
    lead=True also neutralises leading markdown (> # - *) in a display name.
    """
    text = _flatten(value)[:_MAX_FIELD * 3]
    out = ["\\"] if lead and text[:1] in (">", "#", "-", "*") else []
    size = len(out)
    for match in _TOKEN.finditer(text):
        piece = _REPLACE.get(match.group(), match.group())
        if size + len(piece) > _MAX_FIELD:
            break
        out.append(piece)
        size += len(piece)
    return "".join(out)


def _clean_email(value: str | None) -> str:
    """An email goes in a code span: copies cleanly, can't ping or link."""
    return "`" + _flatten(value).replace("`", "")[:_MAX_FIELD] + "`"


def _frontend_url() -> str:
    url = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    if url.startswith("https://") and len(url) > len("https://") and not _BAD_URL.search(url):
        return url
    return _DEFAULT_FRONTEND


def _post(text: str) -> bool:
    token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip()
    channel = (os.getenv("APPROVAL_ALERT_CHANNEL_ID") or "").strip()
    if not token:
        _warn_once("DISCORD_BOT_TOKEN", "missing")
        return False
    if not (channel.isascii() and channel.isdigit()):
        _warn_once("APPROVAL_ALERT_CHANNEL_ID", "missing" if not channel else "not all digits")
        return False
    if not _take_slot():
        return False
    try:
        response = httpx.post(
            _API.format(channel=channel),
            headers={"Authorization": f"Bot {token}"},
            json={"content": text, "allowed_mentions": {"parse": []}},
            timeout=_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        # Class name only: never headers, never the token.
        logger.warning("Discord alert failed: %s", type(exc).__name__)
        return False
    if 200 <= response.status_code < 300:
        return True
    logger.warning("Discord alert rejected: HTTP %s", response.status_code)
    return False


def send_approval_alert(full_name: str | None, email: str) -> bool:
    """Tell the owner a new sign-in is waiting. True when Discord accepted it."""
    try:
        text = (
            "New sign-in waiting for approval\n"
            f"{_clean(full_name, lead=True) or 'No name'} \xb7 {_clean_email(email)}\n"
            f"Approve or decline: {_frontend_url()}/settings/users"
        )
        return _post(text)
    except Exception as exc:
        logger.warning("Discord alert failed: %s", type(exc).__name__)
        return False


def send_lockout_alert(username: str) -> bool:
    """Tell the owner an account was locked for 15 minutes. True when Discord accepted it."""
    try:
        text = (
            "Sign-in locked for 15 minutes\n"
            f"Account: {_clean(username)}\n"
            "5 wrong passwords in a row. If this wasn't you or someone you know, "
            "no action is needed; the lock clears by itself."
        )
        return _post(text)
    except Exception as exc:
        logger.warning("Discord alert failed: %s", type(exc).__name__)
        return False
