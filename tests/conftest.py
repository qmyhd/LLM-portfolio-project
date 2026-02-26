"""
Pytest configuration and shared fixtures for the test suite.

Provides:
- Mocked OpenAI client fixtures for regression tests
- Pytest markers for test categorization
- Shared database mock fixtures
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch


from typing import Optional


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
