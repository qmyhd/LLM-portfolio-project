"""Tests for app.identity: resolving the calling user and role from X-App-User."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

from app import identity
from app.identity import (
    OWNER_VIEWER,
    PENDING_VIEWER,
    ROLE_RANK,
    ROLES,
    VIEWER_CACHE_SECONDS,
    Viewer,
    invalidate_viewer,
    resolve_viewer,
)

pytestmark = pytest.mark.anyio

USER_ID = str(uuid.uuid4())


def make_request(user_id: str | None = None) -> Request:
    headers = []
    if user_id is not None:
        headers.append((b"x-app-user", user_id.encode()))
    return Request({"type": "http", "headers": headers})


def rows(role: str):
    row = MagicMock()
    row._mapping = {"role": role}
    return [row]


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for name in ("DISABLE_AUTH", "APP_USER_LEGACY_OK", "ENVIRONMENT", "API_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("API_SECRET_KEY", "test-key")
    invalidate_viewer()
    yield
    invalidate_viewer()


async def test_no_header_is_pending():
    with patch("app.identity.execute_sql") as sql:
        viewer = await resolve_viewer(make_request())
    sql.assert_not_called()
    assert viewer.role == "pending"
    assert viewer.user_id is None


async def test_unknown_id_is_pending():
    with patch("app.identity.execute_sql", return_value=[]):
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.role == "pending"


async def test_malformed_id_is_pending_without_db():
    with patch("app.identity.execute_sql") as sql:
        viewer = await resolve_viewer(make_request("x'; drop"))
    assert viewer.role == "pending"
    sql.assert_not_called()


async def test_known_guest_resolves():
    with patch("app.identity.execute_sql", return_value=rows("guest")):
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.role == "guest"
    assert viewer.user_id == USER_ID
    assert viewer.sees_money is False
    assert viewer.is_owner is False


async def test_owner_sees_money():
    with patch("app.identity.execute_sql", return_value=rows("owner")):
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.is_owner is True
    assert viewer.sees_money is True


async def test_family_does_not_see_money():
    with patch("app.identity.execute_sql", return_value=rows("family")):
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.sees_money is False


async def test_cache_hit_skips_db():
    with patch("app.identity.execute_sql", return_value=rows("guest")) as sql:
        await resolve_viewer(make_request(USER_ID))
        await resolve_viewer(make_request(USER_ID))
    assert sql.call_count == 1


async def test_cache_expires_after_30s():
    clock = [1000.0]
    with patch.object(identity, "_now", lambda: clock[0]):
        with patch("app.identity.execute_sql", return_value=rows("guest")) as sql:
            assert (await resolve_viewer(make_request(USER_ID))).role == "guest"
            clock[0] += VIEWER_CACHE_SECONDS + 1
            sql.return_value = rows("family")
            assert (await resolve_viewer(make_request(USER_ID))).role == "family"
            assert sql.call_count == 2


async def test_invalidate_drops_entry():
    with patch("app.identity.execute_sql", return_value=rows("guest")) as sql:
        await resolve_viewer(make_request(USER_ID))
        invalidate_viewer(USER_ID)
        sql.return_value = rows("owner")
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.role == "owner"
    assert sql.call_count == 2


async def test_disable_auth_is_owner(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "true")
    with patch("app.identity.execute_sql") as sql:
        viewer = await resolve_viewer(make_request())
    assert viewer.role == "owner"
    sql.assert_not_called()


async def test_legacy_flag_makes_headerless_owner(monkeypatch):
    monkeypatch.setenv("APP_USER_LEGACY_OK", "1")
    with patch("app.identity.execute_sql") as sql:
        viewer = await resolve_viewer(make_request())
    assert viewer.role == "owner"
    sql.assert_not_called()


async def test_legacy_flag_does_not_cover_unknown_id(monkeypatch):
    monkeypatch.setenv("APP_USER_LEGACY_OK", "1")
    with patch("app.identity.execute_sql", return_value=[]):
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.role == "pending"


async def test_db_error_is_pending_and_not_cached():
    with patch("app.identity.execute_sql", side_effect=RuntimeError("db down")) as sql:
        viewer = await resolve_viewer(make_request(USER_ID))
        assert viewer.role == "pending"
        sql.side_effect = None
        sql.return_value = rows("guest")
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.role == "guest"
    assert sql.call_count == 2


async def test_unknown_role_value_is_pending():
    with patch("app.identity.execute_sql", return_value=rows("editor")):
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.role == "pending"


async def test_expired_entries_are_swept_on_write():
    clock = [1000.0]
    other = str(uuid.uuid4())
    with patch.object(identity, "_now", lambda: clock[0]):
        with patch("app.identity.execute_sql", return_value=rows("guest")):
            await resolve_viewer(make_request(other))
            clock[0] += VIEWER_CACHE_SECONDS + 1
            await resolve_viewer(make_request(USER_ID))
    assert list(identity._cache) == [USER_ID]


async def test_cache_is_capped(monkeypatch):
    monkeypatch.setattr(identity, "VIEWER_CACHE_MAX", 3)
    with patch("app.identity.execute_sql", return_value=rows("guest")):
        for _ in range(10):
            await resolve_viewer(make_request(str(uuid.uuid4())))
            assert len(identity._cache) <= 3


async def test_invalidate_during_lookup_does_not_cache_stale_role():
    def racing_query(*args, **kwargs):
        invalidate_viewer(USER_ID)
        return rows("guest")

    with patch("app.identity.execute_sql", side_effect=racing_query) as sql:
        assert (await resolve_viewer(make_request(USER_ID))).role == "guest"
        sql.side_effect = None
        sql.return_value = rows("owner")
        assert (await resolve_viewer(make_request(USER_ID))).role == "owner"
    assert sql.call_count == 2


async def test_uppercase_uuid_shares_cache_entry():
    with patch("app.identity.execute_sql", return_value=rows("guest")) as sql:
        await resolve_viewer(make_request(USER_ID))
        viewer = await resolve_viewer(make_request(USER_ID.upper()))
    assert viewer.user_id == USER_ID
    assert sql.call_count == 1


async def test_disable_auth_wins_over_header(monkeypatch):
    monkeypatch.setenv("DISABLE_AUTH", "true")
    with patch("app.identity.execute_sql") as sql:
        viewer = await resolve_viewer(make_request(USER_ID))
    assert viewer.role == "owner"
    sql.assert_not_called()


async def test_unknown_id_pending_is_cached():
    with patch("app.identity.execute_sql", return_value=[]) as sql:
        await resolve_viewer(make_request(USER_ID))
        await resolve_viewer(make_request(USER_ID))
    assert sql.call_count == 1


def test_constants():
    assert ROLES == ("pending", "guest", "family", "owner")
    assert ROLE_RANK == {"pending": 0, "guest": 1, "family": 1, "owner": 3}
    assert VIEWER_CACHE_SECONDS == 30
    assert OWNER_VIEWER == Viewer(None, "owner")
    assert PENDING_VIEWER == Viewer(None, "pending")
