"""The test-suite database guard (tests/conftest.py) really blocks real databases.

Background: on 11/12 five tests patched `src.db.execute_sql` while the code under
test had imported `execute_sql` into its own module. The patch missed, and the
tests ran once against the live database. These tests pin the guard that stops it.
"""

import asyncio
import types

import pytest
from sqlalchemy import create_engine, text

import src.db as db
from src.config import get_database_url
# Not imported from conftest: pytest loads that module under its own name, so a second
# import would build a second copy of the guard and its exception class.
DB_GUARD_SENTINEL_URL = "postgresql://test-guard:blocked@127.0.0.1:1/blocked"
BLOCKED = "real database access blocked"


def test_execute_sql_without_patch_is_blocked():
    with pytest.raises(AssertionError, match=f"test_execute_sql_without_patch.*{BLOCKED}"):
        db.execute_sql("SELECT 1")


def test_execute_sql_bulk_path_is_blocked():
    with pytest.raises(AssertionError, match=BLOCKED):
        db.execute_sql("INSERT INTO t VALUES (:a)", params=[{"a": 1}])


def test_get_connection_is_blocked():
    with pytest.raises(AssertionError, match=BLOCKED):
        db.get_connection()


def test_transaction_is_blocked():
    with pytest.raises(AssertionError, match=BLOCKED):
        with db.transaction():
            pass


def test_async_engine_is_blocked():
    with pytest.raises(AssertionError, match=BLOCKED):
        asyncio.run(db.get_async_engine())


def test_populated_engine_cache_is_cleared(monkeypatch):
    # The fixture ran first and emptied the cache; a stale engine cannot be reused.
    assert db._sync_engine is None
    assert db._async_engine is None


def test_psycopg2_connect_is_blocked():
    psycopg2 = pytest.importorskip("psycopg2")
    with pytest.raises(AssertionError, match=BLOCKED):
        psycopg2.connect(DB_GUARD_SENTINEL_URL)


def test_engine_built_around_the_factories_cannot_connect():
    engine = create_engine("postgresql+psycopg2://u:p@127.0.0.1:1/x")
    with pytest.raises(AssertionError, match=BLOCKED):
        engine.connect()


def test_database_url_is_the_sentinel():
    url = get_database_url()
    assert url == DB_GUARD_SENTINEL_URL
    assert "supabase" not in url.lower()
    assert get_database_url(use_direct=True) == DB_GUARD_SENTINEL_URL


def test_own_sqlite_engine_overrides_the_guard(monkeypatch):
    engine = create_engine("sqlite://")
    monkeypatch.setattr(db, "get_sync_engine", lambda: engine)
    rows = db.execute_sql("SELECT 1 AS one", fetch_results=True)
    assert [tuple(r) for r in rows] == [(1,)]


def test_wrong_patch_target_hits_the_guard_not_a_database(monkeypatch):
    """The 11/12 failure: patch src.db.execute_sql, code imported its own name."""
    mod = types.ModuleType("fake_route_module")
    exec(
        "from src.db import execute_sql\n"
        "def handler():\n"
        "    return execute_sql('SELECT 1', fetch_results=True)\n",
        mod.__dict__,
    )
    # execute_sql was bound at import time, so patching src.db afterwards misses it.
    monkeypatch.setattr("src.db.execute_sql", lambda *a, **k: [("fake",)])
    with pytest.raises(AssertionError, match=BLOCKED):
        mod.handler()


def test_auth_me_with_wrong_patch_target_is_blocked(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr("src.db.execute_sql", lambda *a, **k: [])
    client = TestClient(app, raise_server_exceptions=True)
    with pytest.raises(AssertionError, match=BLOCKED):
        client.get(
            "/auth/me", headers={"X-App-User": "12345678-1234-5678-1234-567812345678"}
        )
