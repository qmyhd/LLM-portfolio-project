"""
Pytest configuration and shared fixtures for the test suite.

Provides:
- Mocked OpenAI client fixtures for regression tests
- Pytest markers for test categorization
- Shared database mock fixtures

DATABASE GUARD: no test may reach a real database (a developer's .env holds the production URL).
- The URL variables are replaced with an unusable sentinel before src.config loads, and
  get_database_url() returns it; every engine/connection path raises DatabaseAccessBlocked.
- Every trip is recorded; a test that trips it fails at teardown even if app code swallowed the
  error, unless it is marked integration or expects_db_guard (tests of the guard itself).
- Tests marked @pytest.mark.integration skip the per-test guard, but still see only the
  sentinel unless ALLOW_REAL_DB_IN_TESTS=1 is set. That flag is all-or-nothing (the real URL is
  never held in memory during ordinary tests): with it set, the session refuses to start if any
  selected test is not marked integration.
- A test that needs a database supplies its own (monkeypatch db.get_sync_engine to SQLite).
"""

import json
import os

from tests._db_guard_const import DB_GUARD_SENTINEL_URL

_ALLOW_REAL_DB = os.environ.get("ALLOW_REAL_DB_IN_TESTS") == "1"

# Replaced before src.config is imported (it calls load_dotenv, which never overrides
# variables already set, and pydantic settings prefer the environment to .env).
if not _ALLOW_REAL_DB:
    for _name in ("DATABASE_URL", "DATABASE_DIRECT_URL", "SUPABASE_URL"):
        os.environ[_name] = DB_GUARD_SENTINEL_URL
    for _name in (
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_ANON_KEY",
        "Supabase_ID",
        "anon_public",
        "service_role",
    ):
        os.environ[_name] = "blocked-by-test-guard"

import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch


from typing import Optional


# =============================================================================
# DATABASE GUARD
# =============================================================================


class DatabaseAccessBlocked(AssertionError):
    """Raised when a test tries to open a real database connection."""


_current_test = {"name": "<no test running>", "exempt": False}

# Session-level record of every trip: (test node id, entry point hit).
_trips: list[tuple[str, str]] = []


def _blocked(what: str):
    _trips.append((_current_test["name"], what))
    raise DatabaseAccessBlocked(
        f"{_current_test['name']}: real database access blocked ({what}). "
        "Mock the call at the name the code under test imported (e.g. patch "
        "'app.auth.execute_sql', not 'src.db.execute_sql'), or monkeypatch "
        "src.db.get_sync_engine to a SQLite engine. Integration tests: "
        "@pytest.mark.integration plus ALLOW_REAL_DB_IN_TESTS=1."
    )


def _install_session_guard():
    """Last line of defence: any Postgres connection attempt through SQLAlchemy fails."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "do_connect")
    def _no_postgres(dialect, conn_rec, cargs, cparams):
        if not _current_test["exempt"] and dialect.name != "sqlite":
            _blocked(f"{dialect.name} connect")


def _patch_set(monkeypatch):
    import src.db as db

    def _no_engine(*_a, **_k):
        _blocked("create_engine")

    def _no_async_engine(*_a, **_k):
        _blocked("create_async_engine")

    def _no_connect(*_a, **_k):
        _blocked("driver connect")

    monkeypatch.setattr(db, "_sync_engine", None)
    monkeypatch.setattr(db, "_async_engine", None)
    # app.main's lifespan runs db.healthcheck() (a real SELECT 1) on every
    # `with TestClient(app)`, and swallows the error. Tests get a no-op instead.
    monkeypatch.setattr(db, "healthcheck", lambda: True)
    monkeypatch.setattr(db, "create_engine", _no_engine)
    monkeypatch.setattr(db, "create_async_engine", _no_async_engine)
    try:
        import psycopg2

        monkeypatch.setattr(psycopg2, "connect", _no_connect)
    except ImportError:
        pass
    try:
        import asyncpg

        monkeypatch.setattr(asyncpg, "connect", _no_connect)
        monkeypatch.setattr(asyncpg, "create_pool", _no_connect)
    except ImportError:
        pass


def _force_sentinel_settings():
    import src.config as config

    config.settings.cache_clear()
    s = config.settings()
    s.DATABASE_URL = DB_GUARD_SENTINEL_URL
    s.DATABASE_DIRECT_URL = DB_GUARD_SENTINEL_URL
    s.SUPABASE_URL = DB_GUARD_SENTINEL_URL
    s.SUPABASE_SERVICE_ROLE_KEY = "blocked-by-test-guard"
    s.SUPABASE_ANON_KEY = "blocked-by-test-guard"


if not _ALLOW_REAL_DB:
    _force_sentinel_settings()
    _install_session_guard()


def _unexpected_trips(node) -> list:
    """Trips recorded for this test that it did not declare (integration / expects_db_guard)."""
    if node.get_closest_marker("integration") or node.get_closest_marker("expects_db_guard"):
        return []
    return [t for t in _trips if t[0] == node.nodeid]


@pytest.fixture(autouse=True)
def database_guard(request, monkeypatch):
    """Fail loudly, naming the test, on any attempt to reach a real database.

    The error can be swallowed by `except Exception` in app code, so teardown also
    fails the test if the guard was tripped during it.
    """
    exempt = request.node.get_closest_marker("integration") is not None
    _current_test["name"] = request.node.nodeid
    _current_test["exempt"] = exempt
    if not exempt:
        _patch_set(monkeypatch)
    yield
    _current_test["exempt"] = False
    bad = _unexpected_trips(request.node)
    if bad:
        pytest.fail(
            f"{request.node.nodeid}: the database guard was tripped ({', '.join(w for _, w in bad)}); "
            "app code may have swallowed the error. Mock the database call properly.",
            pytrace=False,
        )


@pytest.fixture
def db_guard_api():
    """For tests of the guard itself: its trip record and helpers."""
    import types

    return types.SimpleNamespace(
        trips=lambda node_id: [w for n, w in _trips if n == node_id],
        unexpected_trips=_unexpected_trips,
        reset_engines=_patch_set,
    )


# =============================================================================
# ANYIO BACKEND CONFIGURATION
# =============================================================================


@pytest.fixture
def anyio_backend():
    """Use asyncio backend only (trio is not installed)."""
    return "asyncio"


# =============================================================================
# PYTEST MARKERS CONFIGURATION
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "openai: marks tests that require OpenAI API (deselect with '-m \"not openai\"')",
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow running (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers",
        "integration: marks integration tests that may require external services",
    )
    config.addinivalue_line(
        "markers",
        "expects_db_guard: the test trips the database guard on purpose (tests of the guard)",
    )


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """ALLOW_REAL_DB_IN_TESTS=1 turns the sentinel off for the whole session, so only
    integration tests may be selected with it."""
    if not _ALLOW_REAL_DB:
        return
    offenders = [i.nodeid for i in items if i.get_closest_marker("integration") is None]
    if offenders:
        pytest.exit(
            "ALLOW_REAL_DB_IN_TESTS=1 disables the database guard for the whole session, "
            f"but {len(offenders)} selected test(s) are not marked integration "
            f"(first: {offenders[0]}). Run with -m integration, or unset the flag.",
            returncode=4,
        )


# =============================================================================
# OPENAI MOCK FIXTURES
# =============================================================================


@pytest.fixture
def mock_triage_result():
    """Factory fixture for creating mock TriageResult objects."""

    def _create_triage_result(
        is_noise: bool = False,
        has_actionable_content: bool = True,
        tickers_present: Optional[list] = None,
        skip_reason: Optional[str] = None,
    ):
        from src.nlp.schemas import TriageResult

        return TriageResult(
            is_noise=is_noise,
            has_actionable_content=has_actionable_content,
            tickers_present=tickers_present or [],
            skip_reason=skip_reason,
        )

    return _create_triage_result


@pytest.fixture
def mock_parsed_idea():
    """Factory fixture for creating mock ParsedIdea objects."""

    def _create_parsed_idea(
        idea_text: str = "Test idea",
        idea_summary: str = "Test summary",
        primary_symbol: str = "AAPL",
        symbols: Optional[list] = None,
        direction: str = "bullish",
        action: Optional[str] = None,
        instrument: str = "equity",
        labels: Optional[list] = None,
        is_noise: bool = False,
    ):
        from src.nlp.schemas import (
            ParsedIdea,
            Direction,
            InstrumentType,
            Action,
            TimeHorizon,
        )

        # Convert string parameters to enums
        direction_enum = Direction(direction)
        instrument_enum = InstrumentType(instrument)
        action_enum = Action(action) if action else None

        return ParsedIdea(
            idea_text=idea_text,
            idea_summary=idea_summary,
            primary_symbol=primary_symbol,
            symbols=symbols or [primary_symbol] if primary_symbol else [],
            direction=direction_enum,
            action=action_enum,
            instrument=instrument_enum,
            time_horizon=TimeHorizon.UNKNOWN,
            trigger_condition=None,
            levels=[],
            option_type=None,
            strike=None,
            expiry=None,
            premium=None,
            labels=labels or [],
            is_noise=is_noise,
        )

    return _create_parsed_idea


@pytest.fixture
def mock_message_parse_result(mock_parsed_idea):
    """Factory fixture for creating mock MessageParseResult objects."""

    def _create_message_parse_result(
        ideas: Optional[list] = None,
        context_summary: str = "Test context",
        confidence: float = 0.9,
    ):
        from src.nlp.schemas import MessageParseResult

        if ideas is None:
            ideas = [mock_parsed_idea()]
        return MessageParseResult(
            ideas=ideas, context_summary=context_summary, confidence=confidence
        )

    return _create_message_parse_result


@pytest.fixture
def mock_openai_client(mock_triage_result, mock_message_parse_result):
    """
    Fixture that provides a fully mocked OpenAI client.

    Usage:
        def test_something(mock_openai_client):
            with mock_openai_client() as client:
                # client.responses.parse is mocked
                pass
    """

    def _create_mock_client(
        triage_result=None,
        parse_result=None,
        raise_error=False,
        error_message="Mock error",
    ):
        mock_client = MagicMock()

        # Create mock response for triage
        mock_triage_response = Mock()
        if triage_result is None:
            triage_result = mock_triage_result()

        # Set up the output structure that _extract_parsed_result expects
        mock_triage_item = Mock()
        mock_triage_item.parsed = triage_result
        mock_triage_response.output = [mock_triage_item]

        # Create mock response for parse
        mock_parse_response = Mock()
        if parse_result is None:
            parse_result = mock_message_parse_result()

        mock_parse_item = Mock()
        mock_parse_item.parsed = parse_result
        mock_parse_response.output = [mock_parse_item]

        if raise_error:
            mock_client.responses.parse.side_effect = Exception(error_message)
        else:
            # Return triage result first, then parse result
            mock_client.responses.parse.side_effect = [
                mock_triage_response,
                mock_parse_response,
            ]

        return patch("src.nlp.openai_parser.get_client", return_value=mock_client)

    return _create_mock_client


@pytest.fixture
def mock_openai_for_regression():
    """
    Fixture specifically for regression tests that loads responses from fixture files.

    This fixture patches get_client() to return canned responses based on input text.
    """

    def _create_regression_mock(fixture_path: Path, response_key: str = "text"):
        """
        Args:
            fixture_path: Path to JSONL file with test cases
            response_key: Key in the fixture that contains the input text
        """
        # Load fixtures if they exist
        responses = {}
        if fixture_path.exists():
            with open(fixture_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        try:
                            case = json.loads(line)
                            text = case.get(response_key, case.get("content", ""))
                            if "mock_response" in case:
                                responses[text] = case["mock_response"]
                        except json.JSONDecodeError:
                            continue

        def get_mock_client():
            mock_client = MagicMock()

            def parse_side_effect(*args, **kwargs):
                # Return a default successful response
                mock_response = Mock()
                mock_item = Mock()

                # Check if this is a triage or parse call based on text_format
                text_format = kwargs.get("text_format")
                if text_format and "Triage" in str(text_format):
                    from src.nlp.schemas import TriageResult

                    mock_item.parsed = TriageResult(
                        is_noise=False,
                        has_actionable_content=True,
                        tickers_present=[],
                        skip_reason=None,
                    )
                else:
                    from src.nlp.schemas import (
                        MessageParseResult,
                        ParsedIdea,
                        Direction,
                        InstrumentType,
                        TimeHorizon,
                    )

                    mock_item.parsed = MessageParseResult(
                        ideas=[
                            ParsedIdea(
                                idea_text="Mock parsed idea",
                                idea_summary="Mock summary",
                                primary_symbol="TEST",
                                symbols=["TEST"],
                                direction=Direction.NEUTRAL,
                                action=None,
                                instrument=InstrumentType.EQUITY,
                                time_horizon=TimeHorizon.UNKNOWN,
                                trigger_condition=None,
                                levels=[],
                                option_type=None,
                                strike=None,
                                expiry=None,
                                premium=None,
                                labels=[],
                                is_noise=False,
                            )
                        ],
                        context_summary="Mock context",
                        confidence=0.8,
                    )

                mock_response.output = [mock_item]
                return mock_response

            mock_client.responses.parse.side_effect = parse_side_effect
            return mock_client

        return patch("src.nlp.openai_parser.get_client", side_effect=get_mock_client)

    return _create_regression_mock


# =============================================================================
# DATABASE MOCK FIXTURES
# =============================================================================


@pytest.fixture
def mock_db_connection():
    """
    Fixture that provides a mocked database connection.

    Usage:
        def test_db_operation(mock_db_connection):
            with mock_db_connection(return_value=[{"id": 1}]):
                # execute_sql is mocked
                pass
    """

    def _create_mock(return_value=None, raise_error=False, error_message="DB Error"):
        if raise_error:
            return patch("src.db.execute_sql", side_effect=Exception(error_message))
        return patch("src.db.execute_sql", return_value=return_value)

    return _create_mock


# =============================================================================
# FIXTURE PATH HELPERS
# =============================================================================


@pytest.fixture
def fixtures_dir():
    """Return the path to the fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def parser_regression_fixture(fixtures_dir):
    """Return the path to parser regression fixture file."""
    return fixtures_dir / "parser_regression.jsonl"


@pytest.fixture
def triage_regression_fixture(fixtures_dir):
    """Return the path to triage regression fixture file."""
    return fixtures_dir / "triage_regression.jsonl"


# =============================================================================
# ACCESS POLICY
# =============================================================================


@pytest.fixture(autouse=True)
def _owner_viewer_for_route_tests():
    """Resolve every API caller as the owner so route tests pass the access policy.

    tests/test_access_matrix.py overrides this per test; tests/test_identity.py
    calls resolve_viewer directly and is unaffected. The app is imported here
    (not skipped when absent from sys.modules) because many tests import it
    inside their own body after this fixture has run and still need the override.
    """
    from app.identity import OWNER_VIEWER, resolve_viewer
    from app.main import app

    saved = dict(app.dependency_overrides)
    app.dependency_overrides[resolve_viewer] = lambda: OWNER_VIEWER
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)


# =============================================================================
# NO REAL DISCORD
# =============================================================================


class _BlockedDiscordHttp:
    """Stands in for httpx inside src.approval_alert: a real post is impossible."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        self.blocked_calls = 0

    def post(self, *args, **kwargs):
        self.blocked_calls += 1
        raise AssertionError(f"{self.test_name}: real Discord post blocked (patch httpx.post)")


@pytest.fixture(autouse=True)
def discord_guard(request, monkeypatch):
    """No test may post to Discord, whatever a developer's .env holds.

    The Discord settings are removed from the environment and the module's
    http client is swapped for one that raises. tests/test_approval_alert.py
    sets its own env values and patches `src.approval_alert.httpx.post`.
    """
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("APPROVAL_ALERT_CHANNEL_ID", raising=False)
    import src.approval_alert as approval_alert

    guard = _BlockedDiscordHttp(request.node.name)
    monkeypatch.setattr(approval_alert, "httpx", guard)
    approval_alert._reset_counter()
    yield guard
