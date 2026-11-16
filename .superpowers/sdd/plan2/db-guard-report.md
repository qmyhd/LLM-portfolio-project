# DB guard report (chore/test-db-guard)

## Implemented
- `tests/conftest.py`: top-of-file env sentinel (`postgresql://test-guard:blocked@127.0.0.1:1/blocked`) for DATABASE_URL,
  DATABASE_DIRECT_URL, SUPABASE_URL, and sentinel strings for SUPABASE_SERVICE_ROLE_KEY / SUPABASE_ANON_KEY and the legacy
  names (Supabase_ID, anon_public, service_role). Set before `src.config` imports (load_dotenv never overrides set vars;
  pydantic prefers env to .env). Settings cache is cleared and fields forced to the sentinel, so `get_database_url()`
  (and `use_direct=True`, `get_migration_database_url`) return the sentinel. Real values are never read or logged.
- Autouse `database_guard` fixture (skips per-test patches for `@pytest.mark.integration`).
- `ALLOW_REAL_DB_IN_TESTS=1` disables the replacement entirely (documented in conftest header and docs/DEV_SETUP.md).
- `tests/test_db_guard.py`: 12 tests. `docs/DEV_SETUP.md`: short section.

## Entry points and coverage
| Entry point | Coverage |
|---|---|
| `db.get_sync_engine` (creates via `create_engine`) | `db.create_engine` stubbed to raise; `_sync_engine` cache set None per test |
| `db.get_async_engine` | `db.create_async_engine` stubbed; `_async_engine` set None |
| `get_connection`, `transaction`, `healthcheck`, `async_healthcheck`, `get_database_size/table_sizes/test_connection` | all go through the two factories |
| `execute_sql` (single and list/bulk paths), `_execute_query` | via `get_sync_engine` |
| Populated engine caches | reset to None by the fixture (restored after the test) |
| `initialize_database` (`psycopg2.connect(get_database_url())`) | `psycopg2.connect` patched; URL is sentinel |
| `asyncpg` (only via SQLAlchemy dialect) | `asyncpg.connect/create_pool` patched |
| Any engine built elsewhere (scripts, a stray `sqlalchemy.create_engine`) | SQLAlchemy `Engine` `do_connect` listener raises for any non-sqlite dialect; plus sentinel URL (127.0.0.1:1) |
| `supabase` client | none in app/ src/ scripts/ (grep: no `create_client`, no `from supabase`); only SUPABASE_* config values, now sentinel |
| `scripts/deploy_database.py`, `scripts/verify_database.py` | use `get_database_url()` / `create_engine`; not imported by tests; covered by sentinel + do_connect |

A test's own `monkeypatch.setattr(db, "get_sync_engine"/"create_engine"/...)` is applied after the fixture and overrides it.
Caveat: a test that patches `src.db.execute_sql` while the code imported its own name now hits the guard (proved in tests).

## Tests changed
None. No existing test failed under the guard, so none was silently reaching a database.

## Full suite
`.venv/Scripts/python -m pytest -q -m "not openai and not integration"` -> 1005 passed, 13 deselected (993 + 12 new).
Warnings are pre-existing (google.generativeai, an unawaited AsyncMock, a pandas deprecation).

## Concerns
- `tests/test_db_guard.py` does not import from conftest (pytest loads it as `conftest`, importing `tests.conftest` would build a second guard copy), so the sentinel is repeated and the error is matched as `AssertionError` by message.
- Integration tests (13 deselected) were not run; any that need a real DB must set ALLOW_REAL_DB_IN_TESTS=1 and run with the guard's env replacement off.

## Fix report (review round)
1. Swallowed errors: `_blocked` now records `(node id, entry point)` in a session list; autouse `database_guard` fails the test at teardown if it tripped and is not `integration`/`expects_db_guard`. Marker registered in conftest `pytest_configure` and `pyproject.toml`. Guard tests carry `expects_db_guard` and assert via the `db_guard_api` fixture. New `test_swallowed_trip_is_still_recorded` (inner `try/except Exception: pass` around `execute_sql`, asserts the record and `_unexpected_trips` on an unmarked stand-in node vs the marked node). Verified separately with a throwaway unmarked swallowing test: it errored at teardown (file deleted).
   Finding: the teardown check immediately errored 123 tests in 18 files. Cause: `app.main` lifespan runs `db.healthcheck()` (a real `SELECT 1`) on every `with TestClient(app)` and swallows the failure, so those route tests were hitting the production database at startup. Fixed centrally, no test edits: the guard fixture patches `src.db.healthcheck` to `lambda: True` (a test's own patch overrides it).
2. `test_populated_engine_cache_is_cleared` now sets both caches to dummy objects, calls the reset helper (`_patch_set`), asserts both None.
3. `tests/_db_guard_const.py` holds the sentinel; conftest and the guard tests import it.
4. Chose the all-or-nothing form (per-test restore would hold the real URL in memory during ordinary tests): `pytest_collection_modifyitems` (trylast) exits with code 4 and a clear message if `ALLOW_REAL_DB_IN_TESTS=1` and any selected test is not `integration`. Verified: flag + test_db_guard.py exits with that message. Comment block and `docs/DEV_SETUP.md` updated.
Result: `tests/test_db_guard.py` 13 passed; full suite 1006 passed, 13 deselected (1005 + 1 new).
