"""
Tests for src/discord_ingest.py — incremental Discord message ingestion.

All tests mock execute_sql and Discord API objects — no external dependencies.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.discord_ingest import (
    IngestResult,
    check_channel_not_running,
    compute_content_hash,
    get_cursor,
    get_ingestion_status,
    set_cursor,
)


# =========================================================================
# compute_content_hash
# =========================================================================


class TestComputeContentHash:
    def test_deterministic(self):
        """Same input always produces the same hash."""
        assert compute_content_hash("hello world") == compute_content_hash("hello world")

    def test_normalises_whitespace(self):
        """Leading/trailing whitespace and multiple spaces are collapsed."""
        assert compute_content_hash("  hello   world  ") == compute_content_hash("hello world")

    def test_case_insensitive(self):
        """Hashing is case-insensitive."""
        assert compute_content_hash("Hello World") == compute_content_hash("hello world")

    def test_empty_string(self):
        """Empty string produces a valid hash."""
        h = compute_content_hash("")
        assert isinstance(h, str)
        assert len(h) == 64  # SHA-256 hex digest length

    def test_known_value(self):
        """Spot-check against known SHA-256 of normalised 'hello world'."""
        import hashlib
        expected = hashlib.sha256("hello world".encode()).hexdigest()
        assert compute_content_hash("Hello  World") == expected

    def test_newlines_collapsed(self):
        """Newlines are treated as whitespace and collapsed."""
        assert compute_content_hash("foo\n\nbar") == compute_content_hash("foo bar")

    def test_different_content_different_hash(self):
        """Different content produces different hashes."""
        assert compute_content_hash("buy AAPL") != compute_content_hash("sell AAPL")


# =========================================================================
# get_cursor
# =========================================================================


class TestGetCursor:
    @patch("src.db.execute_sql")
    def test_returns_cursor_when_exists(self, mock_sql):
        mock_sql.return_value = [("123456789",)]
        assert get_cursor("111") == "123456789"

    @patch("src.db.execute_sql")
    def test_returns_none_when_no_state(self, mock_sql):
        mock_sql.return_value = []
        assert get_cursor("111") is None

    @patch("src.db.execute_sql")
    def test_returns_none_when_cursor_is_null(self, mock_sql):
        mock_sql.return_value = [(None,)]
        assert get_cursor("111") is None


# =========================================================================
# set_cursor
# =========================================================================


class TestSetCursor:
    @patch("src.db.execute_sql")
    def test_upsert_called_with_correct_params(self, mock_sql):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        set_cursor("111", "trading", "999", ts, 5, 2)
        mock_sql.assert_called_once()
        call_params = mock_sql.call_args[0][1]
        assert call_params["cid"] == "111"
        assert call_params["cname"] == "trading"
        assert call_params["mid"] == "999"
        assert call_params["new_count"] == 5
        assert call_params["dupe_count"] == 2


# =========================================================================
# check_channel_not_running
# =========================================================================


class TestCheckChannelNotRunning:
    @patch("src.db.execute_sql")
    def test_no_state_returns_true(self, mock_sql):
        mock_sql.return_value = []
        assert check_channel_not_running("111") is True

    @patch("src.db.execute_sql")
    def test_idle_returns_true(self, mock_sql):
        mock_sql.return_value = [("idle", datetime.now(timezone.utc), 5.0)]
        assert check_channel_not_running("111") is True

    @patch("src.db.execute_sql")
    def test_error_returns_true(self, mock_sql):
        mock_sql.return_value = [("error", datetime.now(timezone.utc), 10.0)]
        assert check_channel_not_running("111") is True

    @patch("src.db.execute_sql")
    def test_running_recent_returns_false(self, mock_sql):
        mock_sql.return_value = [("running", datetime.now(timezone.utc), 5.0)]
        assert check_channel_not_running("111") is False

    @patch("src.db.execute_sql")
    def test_running_stale_returns_true(self, mock_sql):
        mock_sql.return_value = [("running", datetime.now(timezone.utc), 35.0)]
        assert check_channel_not_running("111") is True


# =========================================================================
# IngestResult
# =========================================================================


class TestIngestResult:
    def test_default_values(self):
        r = IngestResult(channel_id="111")
        assert r.channel_id == "111"
        assert r.channel_name == ""
        assert r.messages_fetched == 0
        assert r.messages_new == 0
        assert r.messages_duplicate == 0
        assert r.messages_skipped_bot == 0
        assert r.cursor_before is None
        assert r.cursor_after is None
        assert r.error is None
        assert r.dry_run is False
        assert r.duration_seconds == 0.0


# =========================================================================
# ingest_channel (async tests)
# =========================================================================


def _make_mock_message(msg_id, content="test", author_bot=False):
    """Create a mock Discord message."""
    msg = MagicMock()
    msg.id = msg_id
    msg.content = content
    msg.created_at = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    msg.author = MagicMock()
    msg.author.bot = author_bot
    msg.author.name = "testuser"
    msg.author.id = 42
    msg.channel = MagicMock()
    msg.channel.name = "trading"
    msg.channel.id = 111
    msg.reference = None
    msg.mentions = []
    msg.attachments = []
    return msg


def _make_mock_bot(channel=None, messages=None):
    """Create a mock Bot with a channel that yields messages."""
    bot = MagicMock()
    bot.user = MagicMock()
    bot.user.id = 999
    bot.command_prefix = "!"

    if channel is None:
        channel = MagicMock()
        channel.name = "trading"
        channel.id = 111

    if messages is not None:
        async def mock_history(**kwargs):
            for m in messages:
                yield m
        channel.history = mock_history

    bot.get_channel = MagicMock(return_value=channel)
    return bot


# Patch targets for lazy imports inside ingest_channel
_PATCH_CHECK = "src.discord_ingest.check_channel_not_running"
_PATCH_GET_CURSOR = "src.discord_ingest.get_cursor"
_PATCH_SET_CURSOR = "src.discord_ingest.set_cursor"
_PATCH_MARK_STATUS = "src.discord_ingest._mark_channel_status"
_PATCH_LOG_MSG = "src.logging_utils.log_message_to_database"
_PATCH_GET_CHANNEL_TYPE = "src.bot.events.get_channel_type"


class TestIngestChannel:
    @pytest.mark.asyncio
    async def test_dry_run_no_db_writes(self):
        """Dry run should count messages but not write to DB."""
        from src.discord_ingest import ingest_channel

        msgs = [_make_mock_message(1001, "buy AAPL"), _make_mock_message(1002, "sell TSLA")]
        bot = _make_mock_bot(messages=msgs)

        with (
            patch(_PATCH_CHECK, return_value=True),
            patch(_PATCH_GET_CURSOR, return_value=None),
            patch(_PATCH_MARK_STATUS),
            patch(_PATCH_SET_CURSOR) as mock_set,
            patch(_PATCH_LOG_MSG) as mock_log,
            patch(_PATCH_GET_CHANNEL_TYPE, return_value="trading"),
        ):
            result = await ingest_channel(bot, "111", dry_run=True)

        assert result.dry_run is True
        assert result.messages_fetched == 2
        assert result.messages_new == 2
        mock_log.assert_not_called()
        mock_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_permission_error_cursor_not_advanced(self):
        """Permission error should NOT advance cursor."""
        import discord as discord_lib
        from src.discord_ingest import ingest_channel

        channel = MagicMock()
        channel.name = "trading"
        channel.id = 111

        async def mock_history(**kwargs):
            raise discord_lib.Forbidden(MagicMock(status=403), "Missing Access")
            yield  # noqa: B901

        channel.history = mock_history
        bot = _make_mock_bot(channel=channel)

        with (
            patch(_PATCH_CHECK, return_value=True),
            patch(_PATCH_GET_CURSOR, return_value="500"),
            patch(_PATCH_MARK_STATUS) as mock_status,
            patch(_PATCH_SET_CURSOR) as mock_set,
            patch(_PATCH_GET_CHANNEL_TYPE, return_value="trading"),
        ):
            result = await ingest_channel(bot, "111")

        assert result.error is not None
        assert "Permission denied" in result.error
        mock_set.assert_not_called()
        # Should mark channel as running first, then error
        assert mock_status.call_count == 2
        # First call: mark running
        assert mock_status.call_args_list[0][0] == ("111", "running")
        # Second call: mark error
        error_call = mock_status.call_args_list[1][0]
        assert error_call[0] == "111"
        assert error_call[1] == "error"
        assert isinstance(error_call[2], str)

    @pytest.mark.asyncio
    async def test_basic_flow_advances_cursor(self):
        """Normal flow should write messages and advance cursor."""
        from src.discord_ingest import ingest_channel

        msgs = [_make_mock_message(2001, "bullish on NVDA"), _make_mock_message(2002, "AAPL to 200")]
        bot = _make_mock_bot(messages=msgs)

        with (
            patch(_PATCH_CHECK, return_value=True),
            patch(_PATCH_GET_CURSOR, return_value=None),
            patch(_PATCH_MARK_STATUS),
            patch(_PATCH_SET_CURSOR) as mock_set,
            patch(_PATCH_LOG_MSG) as mock_log,
            patch(_PATCH_GET_CHANNEL_TYPE, return_value="trading"),
        ):
            result = await ingest_channel(bot, "111")

        assert result.error is None
        assert result.messages_fetched == 2
        assert result.messages_new == 2
        assert mock_log.call_count == 2
        mock_set.assert_called_once()
        # Cursor should be set to highest message ID
        set_args = mock_set.call_args
        assert set_args[1]["last_message_id"] == "2002"

    @pytest.mark.asyncio
    async def test_concurrent_run_skips(self):
        """If channel is already running, should skip."""
        from src.discord_ingest import ingest_channel

        bot = _make_mock_bot(messages=[])

        with patch(_PATCH_CHECK, return_value=False):
            result = await ingest_channel(bot, "111")

        assert result.error is not None
        assert "Concurrent" in result.error

    @pytest.mark.asyncio
    async def test_skips_self_messages(self):
        """Bot's own messages should be skipped."""
        from src.discord_ingest import ingest_channel

        self_msg = _make_mock_message(3001, "I am the bot")
        bot = _make_mock_bot(messages=[self_msg])
        # Set msg.author == bot.user so the identity check passes
        self_msg.author = bot.user

        with (
            patch(_PATCH_CHECK, return_value=True),
            patch(_PATCH_GET_CURSOR, return_value=None),
            patch(_PATCH_MARK_STATUS),
            patch(_PATCH_SET_CURSOR),
            patch(_PATCH_LOG_MSG) as mock_log,
            patch(_PATCH_GET_CHANNEL_TYPE, return_value="trading"),
        ):
            result = await ingest_channel(bot, "111")

        assert result.messages_skipped_bot == 1
        assert result.messages_new == 0
        mock_log.assert_not_called()

    @pytest.mark.asyncio
    async def test_channel_not_found(self):
        """If channel cannot be resolved, should return error."""
        import discord as discord_lib
        from src.discord_ingest import ingest_channel

        bot = MagicMock()
        bot.user = MagicMock()
        bot.get_channel = MagicMock(return_value=None)
        bot.fetch_channel = AsyncMock(
            side_effect=discord_lib.NotFound(MagicMock(status=404), "Not Found")
        )

        result = await ingest_channel(bot, "999999")

        assert result.error is not None
        assert "Cannot access channel" in result.error


# =========================================================================
# ingest_all_channels
# =========================================================================


class TestIngestAllChannels:
    @pytest.mark.asyncio
    async def test_iterates_all_configured_channels(self):
        """Should call ingest_channel for each channel in config."""
        from src.discord_ingest import ingest_all_channels

        mock_result = IngestResult(channel_id="111", messages_new=5)

        with (
            patch("src.config.settings") as mock_settings,
            patch(
                "src.discord_ingest.ingest_channel",
                new_callable=AsyncMock,
                return_value=mock_result,
            ) as mock_ingest,
        ):
            mock_settings.return_value.log_channel_ids_list = ["111", "222"]
            results = await ingest_all_channels(MagicMock())

        assert len(results) == 2
        assert mock_ingest.call_count == 2

    @pytest.mark.asyncio
    async def test_explicit_channel_ids(self):
        """Should use explicit channel_ids when provided."""
        from src.discord_ingest import ingest_all_channels

        mock_result = IngestResult(channel_id="333", messages_new=0)

        with patch(
            "src.discord_ingest.ingest_channel",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_ingest:
            results = await ingest_all_channels(MagicMock(), channel_ids=["333"])

        assert len(results) == 1
        mock_ingest.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_channel_list(self):
        """Should return empty list when no channels configured."""
        from src.discord_ingest import ingest_all_channels

        with patch("src.config.settings") as mock_settings:
            mock_settings.return_value.log_channel_ids_list = []
            results = await ingest_all_channels(MagicMock())

        assert results == []


# =========================================================================
# get_ingestion_status
# =========================================================================


class TestGetIngestionStatus:
    @patch("src.db.execute_sql")
    def test_returns_dicts(self, mock_sql):
        mock_sql.return_value = [
            ("111", "trading", "999", None, 100, None, 5, 0, "idle", None),
        ]
        rows = get_ingestion_status()
        assert len(rows) == 1
        assert rows[0]["channel_id"] == "111"
        assert rows[0]["channel_name"] == "trading"
        assert rows[0]["status"] == "idle"

    @patch("src.db.execute_sql")
    def test_empty_when_no_state(self, mock_sql):
        mock_sql.return_value = []
        assert get_ingestion_status() == []
