"""
Tests for core utility functions.

Covers:
- Prompt building for journal generation
- JSON formatting for holdings and prices
"""

import json
import pytest
import pandas as pd

from src.journal_generator import (
    create_journal_prompt,
    format_holdings_as_json,
    format_prices_as_json,
)


# =============================================================================
# PROMPT BUILDER TESTS
# =============================================================================


class TestFormatHoldingsAsJson:
    """Test formatting holdings as JSON."""

    def test_format_holdings_basic(self):
        """Test formatting holdings as JSON."""
        positions_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "quantity": [10, 5],
                "equity": [1500, 1000],
                "price": [150, 200],
                "average_buy_price": [120, 180],
            }
        )

        json_str = format_holdings_as_json(positions_df)
        holdings = json.loads(json_str)

        assert "holdings" in holdings
        assert len(holdings["holdings"]) == 2

        aapl = holdings["holdings"][0]
        assert aapl["symbol"] == "AAPL"
        assert aapl["quantity"] == 10
        assert aapl["equity"] == 1500

    def test_format_holdings_empty(self):
        """Test with empty DataFrame."""
        empty_df = pd.DataFrame()
        empty_json = format_holdings_as_json(empty_df)
        empty_holdings = json.loads(empty_json)
        assert empty_holdings["holdings"] == []


class TestFormatPricesAsJson:
    """Test formatting prices as JSON with net change."""

    def test_format_prices_basic(self):
        """Test formatting prices as JSON with net change included."""
        prices_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "price": [150, 200],
                "previous_close": [145, 205],
                "timestamp": ["2025-09-19", "2025-09-19"],
            }
        )

        json_str = format_prices_as_json(prices_df)
        prices = json.loads(json_str)

        assert "prices" in prices
        assert len(prices["prices"]) == 2

        aapl = prices["prices"][0]
        assert aapl["symbol"] == "AAPL"
        assert aapl["price"] == 150
        assert aapl["previous_close"] == 145
        assert aapl["net_change"] == 5  # 150 - 145
        assert aapl["percent_change"] == pytest.approx(3.4482758620689653)

        msft = prices["prices"][1]
        assert msft["net_change"] == -5  # 200 - 205
        assert msft["percent_change"] == pytest.approx(-2.4390243902439024)

    def test_format_prices_empty(self):
        """Test with empty DataFrame."""
        empty_df = pd.DataFrame()
        empty_json = format_prices_as_json(empty_df)
        empty_prices = json.loads(empty_json)
        assert empty_prices["prices"] == []


class TestCreateJournalPrompt:
    """Test journal prompt creation with all components."""

    def test_create_prompt_with_data(self):
        """Test journal prompt creation with all components."""
        positions_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "quantity": [10, 5],
                "equity": [1500, 1000],
                "price": [150, 200],
                "average_buy_price": [120, 180],
            }
        )

        prices_df = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT"],
                "price": [150, 200],
                "previous_close": [145, 205],
                "timestamp": ["2025-09-19", "2025-09-19"],
            }
        )

        messages_df = pd.DataFrame(
            {
                "content": ["$AAPL looking good!", "$MSFT is overvalued"],
                "created_at": ["2025-09-19", "2025-09-19"],
                "tickers_detected": ["$AAPL", "$MSFT"],
            }
        )

        prompt = create_journal_prompt(positions_df, messages_df, prices_df)

        assert "<holdings>" in prompt
        assert "</holdings>" in prompt
        assert "<prices>" in prompt
        assert "</prices>" in prompt
        assert "$AAPL looking good!" in prompt
        assert "$MSFT is overvalued" in prompt

    def test_create_prompt_empty_data(self):
        """Test with empty DataFrames."""
        empty_prompt = create_journal_prompt(
            pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
        )
        assert "N/A" in empty_prompt
