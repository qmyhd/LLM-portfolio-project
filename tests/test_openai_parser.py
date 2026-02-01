"""
Tests for src/nlp/openai_parser.py

Focuses on:
- ParseFailure exception behavior
- Retry/escalation logic
- Status='error' when parsing fails (never 'ok' with fallback data)
- Debug diagnostics
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.nlp.openai_parser import (
    ParseFailure,
    set_debug_openai,
    _extract_parsed_result,
    _diagnose_response_failure,
)


class TestParseFailureException:
    """Tests for the ParseFailure exception class."""

    def test_parse_failure_basic(self):
        """ParseFailure should be a regular exception."""
        exc = ParseFailure("Test message")
        assert str(exc) == "Test message"
        assert exc.raw_output is None

    def test_parse_failure_with_raw_output(self):
        """ParseFailure should capture raw_output for diagnostics."""
        exc = ParseFailure("Test message", raw_output='{"unexpected": "json"}')
        assert exc.raw_output == '{"unexpected": "json"}'

    def test_parse_failure_is_exception(self):
        """ParseFailure should be catchable as Exception."""
        try:
            raise ParseFailure("Test")
        except Exception as e:
            assert isinstance(e, ParseFailure)


class TestDebugMode:
    """Tests for debug mode flag."""

    def test_set_debug_openai_enables_flag(self):
        """set_debug_openai(True) should enable the module flag."""
        from src.nlp import openai_parser

        original = openai_parser.DEBUG_OPENAI
        try:
            set_debug_openai(True)
            assert openai_parser.DEBUG_OPENAI is True
            set_debug_openai(False)
            assert openai_parser.DEBUG_OPENAI is False
        finally:
            openai_parser.DEBUG_OPENAI = original


class TestExtractParsedResult:
    """Tests for _extract_parsed_result function."""

    def test_returns_none_when_no_output(self):
        """Should return None when response has no output."""
        mock_response = Mock()
        mock_response.output = None

        result = _extract_parsed_result(mock_response, dict)
        assert result is None

    def test_returns_none_when_empty_output(self):
        """Should return None when output is empty list."""
        mock_response = Mock()
        mock_response.output = []

        result = _extract_parsed_result(mock_response, dict)
        assert result is None


class TestDiagnoseResponseFailure:
    """Tests for _diagnose_response_failure helper."""

    def test_diagnose_logs_structure(self):
        """Should log response structure for debugging."""
        mock_response = Mock()
        mock_response.output = None

        result = _diagnose_response_failure(mock_response, dict)
        assert isinstance(result, str)
        assert "dict" in result


class TestTriageRetryBehavior:
    """Tests for triage_message retry behavior."""

    @patch("src.nlp.openai_parser.get_client")
    def test_triage_raises_parse_failure_after_retry(self, mock_get_client):
        """triage_message should raise ParseFailure after retry fails."""
        from src.nlp.openai_parser import triage_message

        mock_client = Mock()
        mock_response = Mock()
        mock_response.output = []
        mock_client.responses.parse.return_value = mock_response
        mock_get_client.return_value = mock_client

        with pytest.raises(ParseFailure) as exc_info:
            triage_message("Test message", allow_retry=True)

        assert "retry" in str(exc_info.value).lower()
        assert mock_client.responses.parse.call_count == 2

    @patch("src.nlp.openai_parser.get_client")
    def test_triage_no_retry_when_disabled(self, mock_get_client):
        """triage_message should raise immediately when allow_retry=False."""
        from src.nlp.openai_parser import triage_message

        mock_client = Mock()
        mock_response = Mock()
        mock_response.output = []
        mock_client.responses.parse.return_value = mock_response
        mock_get_client.return_value = mock_client

        with pytest.raises(ParseFailure):
            triage_message("Test message", allow_retry=False)

        assert mock_client.responses.parse.call_count == 1


class TestParseEscalationBehavior:
    """Tests for parse_message escalation behavior."""

    @patch("src.nlp.openai_parser.get_client")
    def test_parse_raises_parse_failure_after_escalation(self, mock_get_client):
        """parse_message should raise ParseFailure after escalation fails."""
        from src.nlp.openai_parser import parse_message

        mock_client = Mock()
        mock_response = Mock()
        mock_response.output = []
        mock_client.responses.parse.return_value = mock_response
        mock_get_client.return_value = mock_client

        with pytest.raises(ParseFailure) as exc_info:
            parse_message("Test message", escalate=False)

        assert "escalation" in str(exc_info.value).lower()
        assert mock_client.responses.parse.call_count == 2


class TestProcessMessageErrorStatus:
    """Tests ensuring process_message returns status='error' on failures."""

    @patch("src.nlp.openai_parser.triage_message")
    @patch("src.nlp.preclean.is_bot_command")
    @patch("src.nlp.soft_splitter.prepare_for_parsing")
    def test_process_returns_error_on_triage_failure(
        self, mock_prepare, mock_is_bot, mock_triage
    ):
        """process_message should return status='error' when triage fails."""
        from src.nlp.openai_parser import process_message
        from src.nlp.soft_splitter import SoftChunk

        mock_is_bot.return_value = False
        mock_prepare.return_value = [
            SoftChunk(
                text="test",
                chunk_type="full",
                start_offset=0,
                end_offset=4,
                detected_tickers=[],
            )
        ]
        mock_triage.side_effect = ParseFailure("Triage failed")

        result = process_message("Test message", message_id="123")

        assert result["status"] == "error"
        assert "Triage failed" in result["error_reason"]
        assert result["ideas"] == []

    @patch("src.nlp.openai_parser.parse_message")
    @patch("src.nlp.openai_parser.triage_message")
    @patch("src.nlp.preclean.is_bot_command")
    @patch("src.nlp.soft_splitter.prepare_for_parsing")
    def test_process_returns_error_on_parse_failure(
        self, mock_prepare, mock_is_bot, mock_triage, mock_parse
    ):
        """process_message should return status='error' when parsing fails."""
        from src.nlp.openai_parser import process_message
        from src.nlp.soft_splitter import SoftChunk
        from src.nlp.schemas import TriageResult

        mock_is_bot.return_value = False
        mock_prepare.return_value = [
            SoftChunk(
                text="test",
                chunk_type="full",
                start_offset=0,
                end_offset=4,
                detected_tickers=[],
            )
        ]
        mock_triage.return_value = TriageResult(
            is_noise=False,
            has_actionable_content=True,
            tickers_present=[],
            skip_reason=None,
        )
        mock_parse.side_effect = ParseFailure("Parse failed after escalation")

        result = process_message("Test message", message_id="123")

        assert result["status"] == "error"
        assert "Parse failed" in result["error_reason"]
        assert result["ideas"] == []

    @patch("src.nlp.openai_parser.parse_message")
    @patch("src.nlp.preclean.is_bot_command")
    @patch("src.nlp.soft_splitter.prepare_for_parsing")
    def test_process_never_returns_ok_with_empty_ideas_from_failure(
        self, mock_prepare, mock_is_bot, mock_parse
    ):
        """process_message should never return status='ok' if parsing failed."""
        from src.nlp.openai_parser import process_message
        from src.nlp.soft_splitter import SoftChunk

        mock_is_bot.return_value = False
        mock_prepare.return_value = [
            SoftChunk(
                text="test",
                chunk_type="full",
                start_offset=0,
                end_offset=4,
                detected_tickers=[],
            )
        ]
        mock_parse.side_effect = ParseFailure("Parse failed")

        result = process_message("Test message", message_id="123", skip_triage=True)

        assert result["status"] != "ok"
        assert result["status"] == "error"
