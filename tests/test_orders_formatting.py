"""
Tests for orders_view.py formatting functions.

Covers:
- Safe NaN/None handling in format_money, format_pct, format_qty
- Side/status normalization
- Option ticker parsing
- Nearest idea selection (mocked)
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from src.bot.formatting.orders_view import (
    format_money,
    format_pct,
    format_qty,
    normalize_side,
    safe_status,
    best_price,
    is_uuid,
    parse_option_ticker,
    get_display_symbol,
    get_underlying_symbol,
    get_nearest_idea,
    format_idea_for_embed,
    _format_time_delta,
    OrderFormatter,
)


class TestFormatMoney:
    """Test format_money handles edge cases correctly."""

    def test_normal_value(self):
        """Normal monetary values format correctly."""
        result = format_money(1234.56)
        assert "1,234" in result
        assert "56" in result

        result = format_money(100)
        assert "100" in result

    def test_negative_value(self):
        """Negative values show minus sign."""
        result = format_money(-50.5)
        assert "-" in result
        assert "50" in result

    def test_none_returns_na(self):
        """None returns N/A, not 'None' string."""
        result = format_money(None)
        assert result == "N/A"
        assert "None" not in result

    def test_nan_returns_na(self):
        """NaN values return N/A, not 'nan' string."""
        result = format_money(float("nan"))
        assert result == "N/A"
        assert "nan" not in result.lower()

    def test_include_sign_positive(self):
        """Positive values with include_sign show +."""
        result = format_money(100, include_sign=True)
        assert "+" in result
        assert "100" in result

    def test_zero_value(self):
        """Zero formats correctly, not as 'N/A'."""
        result = format_money(0)
        assert "0" in result


class TestFormatPct:
    """Test format_pct handles edge cases correctly."""

    def test_normal_value(self):
        """Normal percentage values format correctly."""
        assert format_pct(12.345) == "+12.35%"
        assert format_pct(-5.0) == "-5.00%"

    def test_none_returns_na(self):
        """None returns N/A."""
        result = format_pct(None)
        assert result == "N/A"
        assert "None" not in result

    def test_nan_returns_na(self):
        """NaN returns N/A."""
        result = format_pct(float("nan"))
        assert result == "N/A"
        assert "nan" not in result.lower()


class TestFormatQty:
    """Test format_qty handles edge cases correctly."""

    def test_whole_number(self):
        """Whole numbers show without decimals."""
        assert format_qty(10.0) == "10"
        assert format_qty(100) == "100"

    def test_fractional_shares(self):
        """Fractional shares show decimals."""
        result = format_qty(0.001228)
        assert "0.001228" in result

    def test_none_returns_na(self):
        """None returns N/A."""
        result = format_qty(None)
        assert result == "N/A"
        assert "None" not in result

    def test_nan_returns_na(self):
        """NaN returns N/A."""
        result = format_qty(float("nan"))
        assert result == "N/A"
        assert "nan" not in result.lower()

    def test_zero_shows_zero(self):
        """Zero quantity shows '0', not 'N/A' or '0.0'."""
        result = format_qty(0)
        assert result == "0"
        assert "N/A" not in result


class TestNormalizeSide:
    """Test action/side normalization."""

    def test_buy_variants(self):
        """Buy variants map to 'Bought'."""
        for action in ["BUY", "BUY_OPEN", "buy", "BOUGHT"]:
            assert normalize_side(action) == "Bought"

    def test_sell_variants(self):
        """Sell variants map to 'Sold'."""
        for action in ["SELL", "SELL_CLOSE", "sell", "SOLD"]:
            assert normalize_side(action) == "Sold"

    def test_none_returns_trade(self):
        """None returns 'Trade', not 'None'."""
        result = normalize_side(None)
        assert result == "Trade"
        assert "None" not in result

    def test_empty_returns_trade(self):
        """Empty string returns 'Trade'."""
        result = normalize_side("")
        assert result == "Trade"


class TestSafeStatus:
    """Test status normalization."""

    def test_executed_variants(self):
        """Executed variants map correctly."""
        assert safe_status({"status": "EXECUTED"}) == "Executed"
        assert safe_status({"status": "FILLED"}) == "Executed"

    def test_canceled_variants(self):
        """Canceled variants map correctly."""
        assert safe_status({"status": "CANCELED"}) == "Canceled"
        assert safe_status({"status": "CANCELLED"}) == "Canceled"

    def test_none_returns_unknown(self):
        """None/empty status returns 'Unknown'."""
        result = safe_status({"status": None})
        assert result == "Unknown"
        assert "None" not in result


class TestIsUuid:
    """Test UUID detection."""

    def test_valid_uuid(self):
        """Valid UUIDs are detected."""
        assert is_uuid("6b4e77ed-a7c7-4012-bae7-3f62e0182828") is True
        assert is_uuid("12345678-1234-1234-1234-123456789abc") is True

    def test_ticker_not_uuid(self):
        """Regular tickers are not UUIDs."""
        assert is_uuid("AAPL") is False
        assert is_uuid("AMZN") is False
        assert is_uuid("BRK.B") is False

    def test_none_not_uuid(self):
        """None is not a UUID."""
        assert is_uuid(None) is False
        assert is_uuid("") is False


class TestParseOptionTicker:
    """Test OCC option ticker parsing."""

    def test_call_option(self):
        """Call options parse correctly."""
        result = parse_option_ticker("AMZN  260123C00290000")
        assert result is not None
        assert result["symbol"] == "AMZN"
        assert result["type"] == "Call"
        assert result["strike"] == pytest.approx(290.0)
        assert "AMZN" in result["display"]
        assert "290" in result["display"]
        assert "C" in result["display"]

    def test_put_option(self):
        """Put options parse correctly."""
        result = parse_option_ticker("SPY   241220P00580000")
        assert result is not None
        assert result["symbol"] == "SPY"
        assert result["type"] == "Put"
        assert result["strike"] == pytest.approx(580.0)

    def test_none_returns_none(self):
        """None input returns None."""
        assert parse_option_ticker(None) is None
        assert parse_option_ticker("") is None

    def test_invalid_format(self):
        """Invalid format returns None."""
        assert parse_option_ticker("AAPL") is None
        assert parse_option_ticker("not-an-option") is None


class TestGetDisplaySymbol:
    """Test display symbol resolution."""

    def test_regular_symbol(self):
        """Regular symbols return as-is."""
        order = {"symbol": "AAPL", "option_ticker": None}
        assert get_display_symbol(order) == "AAPL"

    def test_uuid_with_option_ticker(self):
        """UUID symbols use option_ticker display."""
        order = {
            "symbol": "6b4e77ed-a7c7-4012-bae7-3f62e0182828",
            "option_ticker": "AMZN  260123C00290000",
        }
        result = get_display_symbol(order)
        assert "AMZN" in result
        assert "290" in result

    def test_uuid_without_option_ticker(self):
        """UUID without option_ticker returns 'Option'."""
        order = {
            "symbol": "6b4e77ed-a7c7-4012-bae7-3f62e0182828",
            "option_ticker": None,
        }
        assert get_display_symbol(order) == "Option"


class TestFormatTimeDelta:
    """Test time delta formatting."""

    def test_same_time(self):
        """Very small deltas show 'same time'."""
        assert _format_time_delta(30) == "same time"

    def test_minutes(self):
        """Minutes format correctly."""
        assert _format_time_delta(300) == "+5m"
        assert _format_time_delta(-1800) == "-30m"

    def test_hours(self):
        """Hours format correctly."""
        assert _format_time_delta(7200) == "+2h"
        assert _format_time_delta(-3600) == "-1h"

    def test_days(self):
        """Days format correctly."""
        assert _format_time_delta(172800) == "+2d"
        assert _format_time_delta(-86400) == "-1d"


class TestNearestIdeaSelection:
    """Test nearest idea selection with mocked database."""

    @patch("src.db.execute_sql")
    def test_finds_nearest_idea(self, mock_sql):
        """Nearest idea is found and formatted correctly."""
        mock_sql.return_value = [
            (
                "AAPL looks bullish with strong support at $180",
                0.85,
                datetime.now(),
                -7200,
            )
        ]

        result = get_nearest_idea("AAPL", datetime.now())

        assert result is not None
        assert result["idea_text"] == "AAPL looks bullish with strong support at $180"
        assert result["confidence"] == pytest.approx(0.85, abs=0.01)
        assert result["time_delta_str"] == "-2h"

    @patch("src.db.execute_sql")
    def test_no_matching_idea(self, mock_sql):
        """No match returns None."""
        mock_sql.return_value = []

        result = get_nearest_idea("AAPL", datetime.now())
        assert result is None

    @patch("src.db.execute_sql")
    def test_database_error_returns_none(self, mock_sql):
        """Database errors return None gracefully."""
        mock_sql.side_effect = Exception("DB error")

        result = get_nearest_idea("AAPL", datetime.now())
        assert result is None

    def test_none_inputs(self):
        """None inputs return None."""
        assert get_nearest_idea("", datetime.now()) is None  # type: ignore[arg-type]
        assert get_nearest_idea("AAPL", None) is None  # type: ignore[arg-type]


class TestFormatIdeaForEmbed:
    """Test idea formatting for embed display."""

    def test_formats_correctly(self):
        """Idea formats with quotes, confidence, and delta."""
        idea = {
            "idea_text": "AAPL looks bullish",
            "confidence": 0.85,
            "time_delta_str": "-2d",
        }
        result = format_idea_for_embed(idea)
        assert result is not None
        assert '"AAPL looks bullish"' in result
        assert "conf 0.85" in result
        assert "-2d" in result

    def test_truncates_long_text(self):
        """Long text is truncated."""
        idea = {
            "idea_text": "A" * 300,
            "confidence": 0.5,
            "time_delta_str": "+1d",
        }
        result = format_idea_for_embed(idea, max_length=100)
        assert result is not None
        assert len(result) <= 150
        assert "..." in result

    def test_none_returns_none(self):
        """None idea returns None."""
        assert format_idea_for_embed(None) is None


class TestOrderFormatter:
    """Test OrderFormatter class."""

    def test_basic_order(self):
        """Basic order formats correctly."""
        order = {
            "symbol": "AAPL",
            "action": "BUY",
            "status": "EXECUTED",
            "execution_price": 150.00,
            "filled_quantity": 10,
            "order_type": "MARKET",
            "time_executed": datetime.now(),
            "brokerage_order_id": "abc12345678",
        }
        formatter = OrderFormatter(order, current_price=155.00)

        assert formatter.symbol == "AAPL"
        assert formatter.action_display == "Bought"
        assert formatter.status_display == "Executed"

    def test_option_order(self):
        """Option orders detect and display correctly."""
        order = {
            "symbol": "6b4e77ed-a7c7-4012-bae7-3f62e0182828",
            "option_ticker": "AMZN  260123C00290000",
            "action": "BUY_OPEN",
            "status": "EXECUTED",
        }
        formatter = OrderFormatter(order)

        assert formatter.is_option is True
        assert "AMZN" in formatter.symbol
        assert formatter.underlying_symbol == "AMZN"

    def test_to_embed_dict_no_nan(self):
        """Embed dict never contains 'nan' or 'None' strings."""
        order = {
            "symbol": "AAPL",
            "action": "BUY",
            "status": "EXECUTED",
            "execution_price": None,
            "filled_quantity": None,
        }
        formatter = OrderFormatter(order)
        embed = formatter.to_embed_dict(include_idea=False)

        for key, value in embed.items():
            if isinstance(value, str):
                assert "nan" not in value.lower(), f"'nan' found in {key}"
                assert "None" not in value, f"'None' found in {key}"


class TestBestPrice:
    """Test best_price function."""

    def test_executed_order_uses_execution_price(self):
        """Executed orders use execution_price."""
        order = {
            "status": "EXECUTED",
            "execution_price": 150.00,
            "limit_price": 149.00,
        }
        result = best_price(order)
        assert "150" in result

    def test_pending_order_uses_limit_price(self):
        """Pending orders use limit_price."""
        order = {
            "status": "PENDING",
            "execution_price": None,
            "limit_price": 149.00,
        }
        result = best_price(order)
        assert "149" in result

    def test_nan_execution_price_falls_back(self):
        """NaN execution_price falls back to limit_price."""
        order = {
            "status": "EXECUTED",
            "execution_price": float("nan"),
            "limit_price": 149.00,
        }
        result = best_price(order)
        assert "nan" not in result.lower()
