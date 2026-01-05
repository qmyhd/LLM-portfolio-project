#!/usr/bin/env python3
"""
Tests for src/nlp/openai_parser.py

Focuses on:
- ParseFailure exception behavior
- Retry/escalation logic
- Status='error' when parsing fails (never 'ok' with fallback data)
- Debug diagnostics
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.nlp.openai_parser import (
    ParseFailure,
    set_debug_openai,
    _extract_parsed_result,
    _diagnose_response_failure,
)


class TestParseFailureException(unittest.TestCase):
    """Tests for the ParseFailure exception class."""

    def test_parse_failure_basic(self):
        """ParseFailure should be a regular exception."""
        exc = ParseFailure("Test message")
        self.assertEqual(str(exc), "Test message")
        self.assertIsNone(exc.raw_output)

    def test_parse_failure_with_raw_output(self):
        """ParseFailure should capture raw_output for diagnostics."""
        exc = ParseFailure("Test message", raw_output='{"unexpected": "json"}')
        self.assertEqual(exc.raw_output, '{"unexpected": "json"}')

    def test_parse_failure_is_exception(self):
        """ParseFailure should be catchable as Exception."""
        try:
            raise ParseFailure("Test")
        except Exception as e:
            self.assertIsInstance(e, ParseFailure)


class TestDebugMode(unittest.TestCase):
    """Tests for debug mode flag."""

    def test_set_debug_openai_enables_flag(self):
        """set_debug_openai(True) should enable the module flag."""
        from src.nlp import openai_parser

        original = openai_parser.DEBUG_OPENAI
        try:
            set_debug_openai(True)
            self.assertTrue(openai_parser.DEBUG_OPENAI)
            set_debug_openai(False)
            self.assertFalse(openai_parser.DEBUG_OPENAI)
        finally:
            openai_parser.DEBUG_OPENAI = original


class TestExtractParsedResult(unittest.TestCase):
    """Tests for _extract_parsed_result function."""

    def test_returns_none_when_no_output(self):
        """Should return None when response has no output."""
        mock_response = Mock()
        mock_response.output = None

        result = _extract_parsed_result(mock_response, dict)
        self.assertIsNone(result)

    def test_returns_none_when_empty_output(self):
        """Should return None when output is empty list."""
        mock_response = Mock()
        mock_response.output = []

        result = _extract_parsed_result(mock_response, dict)
        self.assertIsNone(result)

    def test_returns_none_when_parsed_missing(self):
        """Should return None when output item has no 'parsed' field."""
        mock_item = Mock()
        mock_item.content = [Mock(text="some text")]
        # No 'parsed' attribute
        del mock_item.parsed  # Ensure it doesn't exist

        mock_response = Mock()
        mock_response.output = [mock_item]

        # Mock hasattr to return False for 'parsed'
        with patch(
            "src.nlp.openai_parser.hasattr",
            side_effect=lambda obj, name: name != "parsed" and hasattr(obj, name),
        ):
            result = _extract_parsed_result(mock_response, dict)

        # The function checks hasattr(item, 'parsed')
        self.assertIsNone(result)


class TestDiagnoseResponseFailure(unittest.TestCase):
    """Tests for _diagnose_response_failure helper."""

    def test_diagnose_logs_structure(self):
        """Should log response structure for debugging."""
        mock_response = Mock()
        mock_response.output = None

        # Should not raise, just return diagnostic string
        result = _diagnose_response_failure(mock_response, dict)
        self.assertIsInstance(result, str)
        self.assertIn("dict", result)  # result_type in message


class TestTriageRetryBehavior(unittest.TestCase):
    """Tests for triage_message retry behavior."""

    @patch("src.nlp.openai_parser.get_client")
    def test_triage_raises_parse_failure_after_retry(self, mock_get_client):
        """triage_message should raise ParseFailure after retry fails."""
        from src.nlp.openai_parser import triage_message

        # Mock client that always returns unparseable responses
        mock_client = Mock()
        mock_response = Mock()
        mock_response.output = []  # Empty output triggers failure
        mock_client.responses.parse.return_value = mock_response
        mock_get_client.return_value = mock_client

        with self.assertRaises(ParseFailure) as ctx:
            triage_message("Test message", allow_retry=True)

        self.assertIn("retry", str(ctx.exception).lower())
        # Should have called parse twice (initial + retry)
        self.assertEqual(mock_client.responses.parse.call_count, 2)

    @patch("src.nlp.openai_parser.get_client")
    def test_triage_no_retry_when_disabled(self, mock_get_client):
        """triage_message should raise immediately when allow_retry=False."""
        from src.nlp.openai_parser import triage_message

        mock_client = Mock()
        mock_response = Mock()
        mock_response.output = []
        mock_client.responses.parse.return_value = mock_response
        mock_get_client.return_value = mock_client

        with self.assertRaises(ParseFailure):
            triage_message("Test message", allow_retry=False)

        # Should have called parse only once
        self.assertEqual(mock_client.responses.parse.call_count, 1)


class TestParseEscalationBehavior(unittest.TestCase):
    """Tests for parse_message escalation behavior."""

    @patch("src.nlp.openai_parser.get_client")
    def test_parse_raises_parse_failure_after_escalation(self, mock_get_client):
        """parse_message should raise ParseFailure after escalation fails."""
        from src.nlp.openai_parser import parse_message

        mock_client = Mock()
        mock_response = Mock()
        mock_response.output = []  # Empty output triggers failure
        mock_client.responses.parse.return_value = mock_response
        mock_get_client.return_value = mock_client

        with self.assertRaises(ParseFailure) as ctx:
            parse_message("Test message", escalate=False)

        self.assertIn("escalation", str(ctx.exception).lower())
        # Should have called parse twice (main + escalation)
        self.assertEqual(mock_client.responses.parse.call_count, 2)


class TestProcessMessageErrorStatus(unittest.TestCase):
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

        self.assertEqual(result["status"], "error")
        self.assertIn("Triage failed", result["error_reason"])
        self.assertEqual(result["ideas"], [])

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

        self.assertEqual(result["status"], "error")
        self.assertIn("Parse failed", result["error_reason"])
        self.assertEqual(result["ideas"], [])

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

        # Key assertion: status must NOT be 'ok' when ParseFailure occurred
        self.assertNotEqual(result["status"], "ok")
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
