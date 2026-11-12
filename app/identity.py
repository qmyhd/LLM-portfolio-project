"""
Identity: resolve which app user is calling the API, and their role.

The Next.js frontend sends the signed-in user's id in the `X-App-User`
header. `resolve_viewer` turns it into a `Viewer` whose role is read from
`app_users` (cached for VIEWER_CACHE_SECONDS). Anything missing, malformed,
unknown or unreadable resolves to `pending` (fail closed).
"""

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass

from fastapi import Request

from app.auth import is_auth_disabled
from src.db import execute_sql

logger = logging.getLogger(__name__)

ROLES: tuple[str, ...] = ("pending", "guest", "family", "owner")
ROLE_RANK: dict[str, int] = {"pending": 0, "guest": 1, "family": 1, "owner": 3}
VIEWER_CACHE_SECONDS = 30
VIEWER_CACHE_MAX = 5000
APP_USER_HEADER = "X-App-User"


@dataclass(frozen=True)
class Viewer:
    user_id: str | None
    role: str

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def sees_money(self) -> bool:
        return self.role == "owner"


OWNER_VIEWER = Viewer(None, "owner")
PENDING_VIEWER = Viewer(None, "pending")

_now = time.monotonic
_cache: dict[str, tuple[float, str]] = {}
_cache_lock = threading.Lock()
_invalidations = 0


def _legacy_ok() -> bool:
    return os.getenv("APP_USER_LEGACY_OK", "").strip().lower() in ("1", "true", "yes")


if _legacy_ok():
    logger.warning(
        "APP_USER_LEGACY_OK is set: requests without X-App-User are treated "
        "as owner. Rollout window only; remove it afterwards."
    )


def invalidate_viewer(user_id: str | None = None) -> None:
    """Drop one cached entry, or the whole cache when no id is given."""
    global _invalidations
    with _cache_lock:
        _invalidations += 1
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop(user_id, None)


def _lookup_role(user_id: str) -> str | None:
    """Return the user's role (pending when unknown/invalid), or None on DB error."""
    now = _now()
    with _cache_lock:
        hit = _cache.get(user_id)
        if hit and now - hit[0] < VIEWER_CACHE_SECONDS:
            return hit[1]
        seen_invalidations = _invalidations

    try:
        rows = execute_sql(
            "SELECT role FROM app_users WHERE id = CAST(:id AS uuid)",
            params={"id": user_id},
            fetch_results=True,
        )
    except Exception:
        logger.warning("Role lookup failed; treating caller as pending", exc_info=True)
        return None

    role = rows[0]._mapping["role"] if rows else "pending"
    if role not in ROLES:
        role = "pending"
    with _cache_lock:
        if _invalidations != seen_invalidations:
            return role  # invalidated mid-lookup: the role may be stale, don't cache
        for key in [k for k, (ts, _) in _cache.items() if now - ts >= VIEWER_CACHE_SECONDS]:
            del _cache[key]
        if len(_cache) >= VIEWER_CACHE_MAX:
            _cache.clear()
        _cache[user_id] = (now, role)
    return role


async def resolve_viewer(request: Request) -> Viewer:
    """FastAPI dependency: the caller's identity and role."""
    if is_auth_disabled():
        return OWNER_VIEWER

    raw = request.headers.get(APP_USER_HEADER)
    if not raw:
        return OWNER_VIEWER if _legacy_ok() else PENDING_VIEWER

    try:
        user_id = str(uuid.UUID(raw.strip()))
    except ValueError:
        return PENDING_VIEWER

    role = _lookup_role(user_id)
    if role is None:
        return PENDING_VIEWER
    return Viewer(user_id, role)
