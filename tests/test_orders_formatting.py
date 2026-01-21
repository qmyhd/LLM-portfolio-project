"""
Tests for orders_view.py formatting functions.

Covers:
- Safe NaN/None handling in format_money, format_pct, format_qty
- Side/status normalization
- Option ticker parsing
- Nearest idea selection (mocked)
"""

import unittest
from datetime import datetime, timedelta
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


class TestFormatMoney(unittest.TestCase):
    """Test format_money handles edge cases correctly."""

    def test_normal_value(self):
        """Normal monetary values format correctly."""
        result = format_money(1234.56)
        self.assertIn("1,234", result)
        self.assertIn("56", result)

        result = format_money(100)
        self.assertIn("100", result)

    def test_negative_value(self):
        """Negative values show minus sign."""
        result = format_money(-50.5)
        self.assertIn("-", result)
        self.assertIn("50", result)

    def test_none_returns_na(self):
        """None returns N/A, not 'None' string."""
        result = format_money(None)
        self.assertEqual(result, "N/A")
        self.assertNotIn("None", result)
        self.assertNotIn("none", result)

    def test_nan_returns_na(self):
        """NaN values return N/A, not 'nan' string."""
        result = format_money(float("nan"))
        self.assertEqual(result, "N/A")
        self.assertNotIn("nan", result.lower())

    def test_include_sign_positive(self):
        """Positive values with include_sign show +."""
        result = format_money(100, include_sign=True)
        self.assertIn("+", result)
        self.assertIn("100", result)

    def test_zero_value(self):
        """Zero formats correctly, not as 'N/A'."""
        # Zero is a valid value, should not be N/A
        result = format_money(0)
        self.assertIn("0", result)


class TestFormatPct(unittest.TestCase):
    """Test format_pct handles edge cases correctly."""

    def test_normal_value(self):
        """Normal percentage values format correctly."""
        self.assertEqual(format_pct(12.345), "+12.35%")
        self.assertEqual(format_pct(-5.0), "-5.00%")

    def test_none_returns_na(self):
        """None returns N/A."""
        result = format_pct(None)
        self.assertEqual(result, "N/A")
        self.assertNotIn("None", result)

    def test_nan_returns_na(self):
        """NaN returns N/A."""
        result = format_pct(float("nan"))
        self.assertEqual(result, "N/A")
        self.assertNotIn("nan", result.lower())


class TestFormatQty(unittest.TestCase):
    """Test format_qty handles edge cases correctly."""

    def test_whole_number(self):
        """Whole numbers show without decimals."""
        self.assertEqual(format_qty(10.0), "10")
        self.assertEqual(format_qty(100), "100")

    def test_fractional_shares(self):
        """Fractional shares show decimals."""
        result = format_qty(0.001228)
        self.assertIn("0.001228", result)

    def test_none_returns_na(self):
        """None returns N/A."""
        result = format_qty(None)
        self.assertEqual(result, "N/A")
        self.assertNotIn("None", result)

    def test_nan_returns_na(self):
        """NaN returns N/A."""
        result = format_qty(float("nan"))
        self.assertEqual(result, "N/A")
        self.assertNotIn("nan", result.lower())

    def test_zero_shows_zero(self):
        """Zero quantity shows '0', not 'N/A' or '0.0'."""
        result = format_qty(0)
        # Zero is a valid qty, should show as "0"
        self.assertEqual(result, "0")
        self.assertNotIn("N/A", result)


class TestNormalizeSide(unittest.TestCase):
    """Test action/side normalization."""

    def test_buy_variants(self):
        """Buy variants map to 'Bought'."""
        for action in ["BUY", "BUY_OPEN", "buy", "BOUGHT"]:
            self.assertEqual(normalize_side(action), "Bought")

    def test_sell_variants(self):
        """Sell variants map to 'Sold'."""
        for action in ["SELL", "SELL_CLOSE", "sell", "SOLD"]:
            self.assertEqual(normalize_side(action), "Sold")

    def test_none_returns_trade(self):
        """None returns 'Trade', not 'None'."""
        result = normalize_side(None)
        self.assertEqual(result, "Trade")
        self.assertNotIn("None", result)

    def test_empty_returns_trade(self):
        """Empty string returns 'Trade'."""
        result = normalize_side("")
        self.assertEqual(result, "Trade")


class TestSafeStatus(unittest.TestCase):
    """Test status normalization."""

    def test_executed_variants(self):
        """Executed variants map correctly."""
        self.assertEqual(safe_status({"status": "EXECUTED"}), "Executed")
        self.assertEqual(safe_status({"status": "FILLED"}), "Executed")

    def test_canceled_variants(self):
        """Canceled variants map correctly."""
        self.assertEqual(safe_status({"status": "CANCELED"}), "Canceled")
        self.assertEqual(safe_status({"status": "CANCELLED"}), "Canceled")

    def test_none_returns_unknown(self):
        """None/empty status returns 'Unknown'."""
        result = safe_status({"status": None})
        self.assertEqual(result, "Unknown")
        self.assertNotIn("None", result)


class TestIsUuid(unittest.TestCase):
    """Test UUID detection."""

    def test_valid_uuid(self):
        """Valid UUIDs are detected."""
        self.assertTrue(is_uuid("6b4e77ed-a7c7-4012-bae7-3f62e0182828"))
        self.assertTrue(is_uuid("12345678-1234-1234-1234-123456789abc"))

    def test_ticker_not_uuid(self):
        """Regular tickers are not UUIDs."""
        self.assertFalse(is_uuid("AAPL"))
        self.assertFalse(is_uuid("AMZN"))
        self.assertFalse(is_uuid("BRK.B"))

    def test_none_not_uuid(self):
        """None is not a UUID."""
        self.assertFalse(is_uuid(None))
        self.assertFalse(is_uuid(""))


class TestParseOptionTicker(unittest.TestCase):
    """Test OCC option ticker parsing."""

    def test_call_option(self):
        """Call options parse correctly."""
        result = parse_option_ticker("AMZN  260123C00290000")
        self.assertEqual(result["symbol"], "AMZN")
        self.assertEqual(result["type"], "Call")
        self.assertEqual(result["strike"], 290.0)
        self.assertIn("AMZN", result["display"])
        self.assertIn("290", result["display"])
        self.assertIn("C", result["display"])

    def test_put_option(self):
        """Put options parse correctly."""
        result = parse_option_ticker("SPY   241220P00580000")
        self.assertEqual(result["symbol"], "SPY")
        self.assertEqual(result["type"], "Put")
        self.assertEqual(result["strike"], 580.0)

    def test_none_returns_none(self):
        """None input returns None."""
        self.assertIsNone(parse_option_ticker(None))
        self.assertIsNone(parse_option_ticker(""))

    def test_invalid_format(self):
        """Invalid format returns None."""
        self.assertIsNone(parse_option_ticker("AAPL"))
        self.assertIsNone(parse_option_ticker("not-an-option"))


class TestGetDisplaySymbol(unittest.TestCase):
    """Test display symbol resolution."""

    def test_regular_symbol(self):
        """Regular symbols return as-is."""
        order = {"symbol": "AAPL", "option_ticker": None}
        self.assertEqual(get_display_symbol(order), "AAPL")

    def test_uuid_with_option_ticker(self):
        """UUID symbols use option_ticker display."""
        order = {
            "symbol": "6b4e77ed-a7c7-4012-bae7-3f62e0182828",
            "option_ticker": "AMZN  260123C00290000",
        }
        result = get_display_symbol(order)
        self.assertIn("AMZN", result)
        self.assertIn("290", result)

    def test_uuid_without_option_ticker(self):
        """UUID without option_ticker returns 'Option'."""
        order = {
            "symbol": "6b4e77ed-a7c7-4012-bae7-3f62e0182828",
            "option_ticker": None,
        }
        self.assertEqual(get_display_symbol(order), "Option")


class TestFormatTimeDelta(unittest.TestCase):
    """Test time delta formatting."""

    def test_same_time(self):
        """Very small deltas show 'same time'."""
        self.assertEqual(_format_time_delta(30), "same time")

    def test_minutes(self):
        """Minutes format correctly."""
        self.assertEqual(_format_time_delta(300), "+5m")  # 5 minutes
        self.assertEqual(_format_time_delta(-1800), "-30m")  # -30 minutes

    def test_hours(self):
        """Hours format correctly."""
        self.assertEqual(_format_time_delta(7200), "+2h")  # 2 hours
        self.assertEqual(_format_time_delta(-3600), "-1h")  # -1 hour

    def test_days(self):
        """Days format correctly."""
        self.assertEqual(_format_time_delta(172800), "+2d")  # 2 days
        self.assertEqual(_format_time_delta(-86400), "-1d")  # -1 day


class TestNearestIdeaSelection(unittest.TestCase):
    """Test nearest idea selection with mocked database."""

    @patch("src.db.execute_sql")
    def test_finds_nearest_idea(self, mock_sql):
        """Nearest idea is found and formatted correctly."""
        # Mock database response
        mock_sql.return_value = [
            (
                "AAPL looks bullish with strong support at $180",
                0.85,
                datetime.now(),
                -7200,
            )
        ]

        result = get_nearest_idea("AAPL", datetime.now())

        self.assertIsNotNone(result)
        self.assertEqual(
            result["idea_text"], "AAPL looks bullish with strong support at $180"
        )
        self.assertAlmostEqual(result["confidence"], 0.85, places=2)
        self.assertEqual(result["time_delta_str"], "-2h")

    @patch("src.db.execute_sql")
    def test_no_matching_idea(self, mock_sql):
        """No match returns None."""
        mock_sql.return_value = []

        result = get_nearest_idea("AAPL", datetime.now())
        self.assertIsNone(result)

    @patch("src.db.execute_sql")
    def test_database_error_returns_none(self, mock_sql):
        """Database errors return None gracefully."""
        mock_sql.side_effect = Exception("DB error")

        result = get_nearest_idea("AAPL", datetime.now())
        self.assertIsNone(result)

    def test_none_inputs(self):
        """None inputs return None."""
        self.assertIsNone(get_nearest_idea(None, datetime.now()))
        self.assertIsNone(get_nearest_idea("AAPL", None))


class TestFormatIdeaForEmbed(unittest.TestCase):
    """Test idea formatting for embed display."""

    def test_formats_correctly(self):
        """Idea formats with quotes, confidence, and delta."""
        idea = {
            "idea_text": "AAPL looks bullish",
            "confidence": 0.85,
            "time_delta_str": "-2d",
        }
        result = format_idea_for_embed(idea)
        self.assertIn('"AAPL looks bullish"', result)
        self.assertIn("conf 0.85", result)
        self.assertIn("-2d", result)

    def test_truncates_long_text(self):
        """Long text is truncated."""
        idea = {
            "idea_text": "A" * 300,
            "confidence": 0.5,
            "time_delta_str": "+1d",
        }
        result = format_idea_for_embed(idea, max_length=100)
        self.assertLessEqual(len(result), 150)  # Including metadata
        self.assertIn("...", result)

    def test_none_returns_none(self):
        """None idea returns None."""
        self.assertIsNone(format_idea_for_embed(None))


class TestOrderFormatter(unittest.TestCase):
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

        self.assertEqual(formatter.symbol, "AAPL")
        self.assertEqual(formatter.action_display, "Bought")
        self.assertEqual(formatter.status_display, "Executed")

    def test_option_order(self):
        """Option orders detect and display correctly."""
        order = {
            "symbol": "6b4e77ed-a7c7-4012-bae7-3f62e0182828",
            "option_ticker": "AMZN  260123C00290000",
            "action": "BUY_OPEN",
            "status": "EXECUTED",
        }
        formatter = OrderFormatter(order)

        self.assertTrue(formatter.is_option)
        self.assertIn("AMZN", formatter.symbol)
        self.assertEqual(formatter.underlying_symbol, "AMZN")

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

        # Check no "nan" or "None" strings in output
        for key, value in embed.items():
            if isinstance(value, str):
                self.assertNotIn("nan", value.lower(), f"'nan' found in {key}")
                self.assertNotIn("None", value, f"'None' found in {key}")


class TestBestPrice(unittest.TestCase):
    """Test best_price function."""

    def test_executed_order_uses_execution_price(self):
        """Executed orders use execution_price."""
        order = {
            "status": "EXECUTED",
            "execution_price": 150.00,
            "limit_price": 149.00,
        }
        result = best_price(order)
        self.assertIn("150", result)

    def test_pending_order_uses_limit_price(self):
        """Pending orders use limit_price."""
        order = {
            "status": "PENDING",
            "execution_price": None,
            "limit_price": 149.00,
        }
        result = best_price(order)
        self.assertIn("149", result)

    def test_nan_execution_price_falls_back(self):
        """NaN execution_price falls back to limit_price."""
        order = {
            "status": "EXECUTED",
            "execution_price": float("nan"),
            "limit_price": 149.00,
        }
        result = best_price(order)
        # Should not contain "nan"
        self.assertNotIn("nan", result.lower())


if __name__ == "__main__":
    unittest.main()
