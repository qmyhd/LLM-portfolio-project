"""A statement that starts with WITH but writes data must be committed.

Found in production on 11/16/2026: the Users API's role change and delete
start with `WITH owners AS (... FOR UPDATE) UPDATE ...`. `_execute_query`
only committed statements that *started* with INSERT/UPDATE/DELETE, so those
ran, returned the changed row, and were rolled back. The API answered 200 and
nothing changed. The route tests mock `execute_sql`, so they could not see it.
"""

import pytest
from sqlalchemy import create_engine, text

import src.db as db


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE t SET a = 1",
        "  insert into t values (1)",
        "DELETE FROM t",
        "CREATE TABLE t (a int)",
        "WITH o AS (SELECT id FROM t FOR UPDATE) UPDATE t SET a = 1 RETURNING a",
        "with o as (select 1) delete from t where a = 1 returning a",
        "WITH x AS (SELECT 1)\nINSERT INTO t SELECT * FROM x",
        "WITH moved AS (DELETE FROM t RETURNING *) SELECT * FROM moved",
    ],
)
def test_writes_need_commit(sql):
    assert db._needs_commit(sql) is True


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT updated_at, deleted FROM t",
        "WITH latest AS (SELECT max(d) FROM t) SELECT * FROM latest",
        "SELECT 'please update me' AS note",
    ],
)
def test_reads_do_not_need_commit(sql):
    assert db._needs_commit(sql) is False


class _SpyEngine:
    """Wraps a real engine and records which path `_execute_query` took.

    SQLite (pysqlite) runs a statement that starts with WITH in autocommit, so
    a change would survive even on the non-committing `connect()` path. The
    persistence tests therefore also assert the path: on Postgres only
    `begin()` commits.
    """

    def __init__(self, engine):
        self._engine = engine
        self.calls: list[str] = []

    def begin(self):
        self.calls.append("begin")
        return self._engine.begin()

    def connect(self):
        self.calls.append("connect")
        return self._engine.connect()


@pytest.fixture
def sqlite_engine(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT)"))
        conn.execute(text("INSERT INTO users VALUES (1, 'owner'), (2, 'pending')"))
    spy = _SpyEngine(engine)
    monkeypatch.setattr(db, "get_sync_engine", lambda: spy)
    engine.spy = spy
    yield engine
    engine.dispose()


def _role(engine, user_id):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT role FROM users WHERE id = :id"), {"id": user_id}
        ).scalar()


def test_cte_update_with_returning_is_persisted(sqlite_engine):
    rows = db.execute_sql(
        """
        WITH owners AS (SELECT id FROM users WHERE role = 'owner')
        UPDATE users SET role = :role
        WHERE id = :id AND (SELECT count(*) FROM owners) >= 1
        RETURNING id, role
        """,
        params={"id": 2, "role": "guest"},
        fetch_results=True,
    )
    assert [tuple(r) for r in rows] == [(2, "guest")]
    # It must take the committing path; on Postgres `connect()` rolls back.
    assert sqlite_engine.spy.calls == ["begin"]
    # A fresh connection must see the change.
    assert _role(sqlite_engine, 2) == "guest"


def test_cte_delete_with_returning_is_persisted(sqlite_engine):
    rows = db.execute_sql(
        """
        WITH owners AS (SELECT id FROM users WHERE role = 'owner')
        DELETE FROM users
        WHERE id = :id AND (SELECT count(*) FROM owners) >= 1
        RETURNING id
        """,
        params={"id": 2},
        fetch_results=True,
    )
    assert [tuple(r) for r in rows] == [(2,)]
    assert sqlite_engine.spy.calls == ["begin"]
    assert _role(sqlite_engine, 2) is None


def test_plain_read_uses_the_read_path(sqlite_engine):
    db.execute_sql("SELECT role FROM users WHERE id = :id", params={"id": 1}, fetch_results=True)
    assert sqlite_engine.spy.calls == ["connect"]


def test_users_api_statements_are_classified_as_writes():
    """The real statements the Users API sends must be committed."""
    import app.routes.users as users

    update_sql = f"""
        {users._OWNERS_CTE}
        UPDATE app_users SET role = :role
        WHERE id = CAST(:id AS uuid)
    """
    delete_sql = f"""
        {users._OWNERS_CTE}
        DELETE FROM app_users
        WHERE id = CAST(:id AS uuid)
    """
    assert db._needs_commit(update_sql) is True
    assert db._needs_commit(delete_sql) is True
