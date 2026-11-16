"""Bound parameters (e.g. argon2 hashes) must not appear in database error text."""

import asyncio

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

import src.db as db

SECRET = "$argon2id$v=19$secret-hash-value"


def test_engine_factories_pass_hide_parameters(monkeypatch):
    seen = {}

    def fake_create_engine(url, **kwargs):
        seen["sync"] = kwargs
        return create_engine("sqlite://")

    def fake_create_async_engine(url, **kwargs):
        seen["async"] = kwargs
        return object()

    class FakeEvent:
        @staticmethod
        def listens_for(*_a, **_k):
            return lambda fn: fn

    monkeypatch.setattr(db, "_sync_engine", None)
    monkeypatch.setattr(db, "_async_engine", None)
    monkeypatch.setattr(db, "get_database_url", lambda: "postgresql://u:p@localhost/db")
    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    monkeypatch.setattr(db, "create_async_engine", fake_create_async_engine)
    monkeypatch.setattr(db, "event", FakeEvent)

    db.get_sync_engine()
    asyncio.run(db.get_async_engine())
    assert seen["sync"]["hide_parameters"] is True
    assert seen["async"]["hide_parameters"] is True


def _failing_insert(engine):
    with pytest.raises(SQLAlchemyError) as exc:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO missing_table (h) VALUES (:h)"), {"h": SECRET})
    return str(exc.value)


def test_failing_statement_error_text_has_no_parameter_value():
    assert SECRET not in _failing_insert(create_engine("sqlite://", hide_parameters=True))
    # Without the setting the value leaks, which is what the setting guards against.
    assert SECRET in _failing_insert(create_engine("sqlite://"))
