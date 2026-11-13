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
_ZWSP = "​"
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  \s]+")

_lock = threading.Lock()
_count_day: date | None = None
_count = 0
_cap_logged_for: date | None = None


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
                logger.warning("Approval alert daily cap of %d reached; sending no more today", MAX_ALERTS_PER_DAY)
            return False
        _count += 1
        return True


def _clean(value: str | None) -> str:
    """Make a stranger-supplied value safe to put in one line of a Discord message."""
    text = _CONTROL.sub(" ", str(value or "")).strip()[:_MAX_FIELD]
    text = text.replace("`", "'")
    text = text.replace("@", "@" + _ZWSP)
    text = text.replace("://", ":/" + _ZWSP + "/")
    text = text.replace("](", "] (")
    return text


def _frontend_url() -> str:
    url = (os.getenv("FRONTEND_URL") or "").strip().rstrip("/")
    return url if url.startswith("https://") and len(url) > len("https://") else _DEFAULT_FRONTEND


def _post(text: str) -> bool:
    token = os.getenv("DISCORD_BOT_TOKEN") or ""
    channel = os.getenv("APPROVAL_ALERT_CHANNEL_ID") or ""
    if not token or not (channel.isascii() and channel.isdigit()):
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
            f"{_clean(full_name) or 'No name'} · {_clean(email)}\n"
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
