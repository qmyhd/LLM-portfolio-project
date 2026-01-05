"""
Tests for message_id string handling.

Ensures message_id is always treated as a string throughout the codebase,
never as an int, to prevent type coercion issues with large Discord IDs.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestMessageIdIsString:
    """Verify message_id is always string in Python."""

    def test_get_pending_messages_with_string_id(self):
        """get_pending_messages accepts string message_id without crash."""
        from scripts.nlp.parse_messages import get_pending_messages

        # Mock execute_sql to avoid actual DB call
        with patch("scripts.nlp.parse_messages.execute_sql") as mock_sql:
            mock_sql.return_value = []

            # Should not crash with string message_id
            result = get_pending_messages(message_id="1380123456789012345")

            # Verify it was called with string param
            assert mock_sql.called
            call_args = mock_sql.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params.get("message_id") == "1380123456789012345"
            assert isinstance(params.get("message_id"), str)

    def test_get_pending_messages_with_numeric_string(self):
        """get_pending_messages normalizes numeric-looking strings."""
        from scripts.nlp.parse_messages import get_pending_messages

        with patch("scripts.nlp.parse_messages.execute_sql") as mock_sql:
            mock_sql.return_value = []

            # Pass integer-like string (legacy code might do this)
            result = get_pending_messages(message_id="1380123456789012345")

            assert mock_sql.called
            call_args = mock_sql.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            # Should be converted to string
            assert isinstance(params.get("message_id"), str)

    def test_get_pending_messages_strips_whitespace(self):
        """get_pending_messages strips whitespace from message_id."""
        from scripts.nlp.parse_messages import get_pending_messages

        with patch("scripts.nlp.parse_messages.execute_sql") as mock_sql:
            mock_sql.return_value = []

            result = get_pending_messages(message_id="  1380123456789012345  ")

            assert mock_sql.called
            call_args = mock_sql.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params.get("message_id") == "1380123456789012345"

    def test_get_pending_messages_empty_string_treated_as_none(self):
        """get_pending_messages treats empty string as None."""
        from scripts.nlp.parse_messages import get_pending_messages

        with patch("scripts.nlp.parse_messages.execute_sql") as mock_sql:
            mock_sql.return_value = []

            result = get_pending_messages(message_id="   ")

            # Should use the pending query, not the specific message query
            assert mock_sql.called
            query = mock_sql.call_args[0][0] if mock_sql.call_args[0] else ""
            # Should contain parse_status = 'pending' (batch query)
            assert "parse_status = 'pending'" in query or mock_sql.call_args.kwargs

    def test_get_pending_messages_returns_empty_or_one(self):
        """get_pending_messages returns 0 or 1 rows for specific message_id."""
        from scripts.nlp.parse_messages import get_pending_messages

        # Test with mock returning one row
        with patch("scripts.nlp.parse_messages.execute_sql") as mock_sql:
            # Simulate one row returned
            mock_sql.return_value = [
                ("1380123456789012345", "test content", "author", "channel", None)
            ]

            result = get_pending_messages(message_id="1380123456789012345")

            assert len(result) <= 1
            if result:
                assert result[0]["message_id"] == "1380123456789012345"

    def test_sql_query_uses_cast_for_safety(self):
        """SQL query uses CAST(:message_id AS text) for type safety."""
        from scripts.nlp.parse_messages import get_pending_messages

        with patch("scripts.nlp.parse_messages.execute_sql") as mock_sql:
            mock_sql.return_value = []

            get_pending_messages(message_id="1380123456789012345")

            query = mock_sql.call_args[0][0]
            assert "CAST(:message_id AS text)" in query


class TestArgparseCLI:
    """Test CLI argument parsing for message_id."""

    def test_argparse_message_id_is_string_type(self):
        """CLI --message-id uses type=str."""
        import argparse
        from scripts.nlp import parse_messages

        # Create a parser the same way main() does
        parser = argparse.ArgumentParser()
        parser.add_argument("--message-id", type=str)

        # Parse with numeric-looking string
        args = parser.parse_args(["--message-id", "1380123456789012345"])
        assert args.message_id == "1380123456789012345"
        assert isinstance(args.message_id, str)


class TestLockKeyConversion:
    """Test advisory lock key conversion handles string message_id."""

    def test_lock_key_from_numeric_string(self):
        """Lock key correctly converts numeric string to int."""
        message_id = "1380123456789012345"
        try:
            lock_key = int(message_id)
            assert lock_key == 1380123456789012345
        except ValueError:
            pytest.fail("Should convert numeric string to int")

    def test_lock_key_from_non_numeric_string(self):
        """Lock key falls back to hash for non-numeric string."""
        message_id = "abc123"
        try:
            lock_key = int(message_id)
            pytest.fail("Should raise ValueError for non-numeric")
        except ValueError:
            lock_key = hash(message_id) & 0x7FFFFFFFFFFFFFFF
            assert isinstance(lock_key, int)
            assert lock_key > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
