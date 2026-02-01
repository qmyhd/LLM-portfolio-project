#!/usr/bin/env python3
"""Test dividend reinvestment (DRIP) detection logic."""

import pytest
from src.bot.formatting.orders_view import (
    OrderFormatter,
    DIVIDEND_REINVESTMENT_THRESHOLD,
)


class TestDividendReinvestmentDetection:
    """Test cases for DRIP detection."""

    def test_threshold_value(self):
        """Verify threshold is set correctly."""
        assert DIVIDEND_REINVESTMENT_THRESHOLD == pytest.approx(2.00)

    def test_small_buy_is_drip(self):
        """Small BUY orders (< $2 notional) should be flagged as DRIP."""
        order = {
            "action": "BUY",
            "execution_price": 10.00,
            "filled_quantity": 0.15,  # Notional = $1.50
            "status": "EXECUTED",
        }
        formatter = OrderFormatter(order)
        assert formatter.notional_value == pytest.approx(1.50)
        assert formatter.is_dividend_reinvestment is True

    def test_normal_buy_not_drip(self):
        """Normal BUY orders (> $2 notional) should NOT be flagged as DRIP."""
        order = {
            "action": "BUY",
            "execution_price": 50.00,
            "filled_quantity": 1.0,  # Notional = $50.00
            "status": "EXECUTED",
        }
        formatter = OrderFormatter(order)
        assert formatter.notional_value == pytest.approx(50.00)
        assert formatter.is_dividend_reinvestment is False

    def test_sell_never_drip(self):
        """SELL orders should NEVER be flagged as DRIP regardless of size."""
        order = {
            "action": "SELL",
            "execution_price": 1.00,
            "filled_quantity": 0.5,  # Notional = $0.50
            "status": "EXECUTED",
        }
        formatter = OrderFormatter(order)
        assert formatter.notional_value == pytest.approx(0.50)
        assert formatter.is_dividend_reinvestment is False

    def test_edge_case_exactly_at_threshold(self):
        """Order exactly at threshold should NOT be flagged (< not <=)."""
        order = {
            "action": "BUY",
            "execution_price": 2.00,
            "filled_quantity": 1.0,  # Notional = $2.00
            "status": "EXECUTED",
        }
        formatter = OrderFormatter(order)
        assert formatter.notional_value == pytest.approx(2.00)
        assert formatter.is_dividend_reinvestment is False

    def test_edge_case_just_under_threshold(self):
        """Order just under threshold should be flagged."""
        order = {
            "action": "BUY",
            "execution_price": 1.99,
            "filled_quantity": 1.0,  # Notional = $1.99
            "status": "EXECUTED",
        }
        formatter = OrderFormatter(order)
        assert formatter.notional_value == pytest.approx(1.99)
        assert formatter.is_dividend_reinvestment is True

    def test_buy_open_is_drip_candidate(self):
        """BUY_OPEN action should also be checked for DRIP."""
        order = {
            "action": "BUY_OPEN",
            "execution_price": 1.50,
            "filled_quantity": 1.0,  # Notional = $1.50
            "status": "EXECUTED",
        }
        formatter = OrderFormatter(order)
        assert formatter.is_dividend_reinvestment is True

    def test_missing_execution_price(self):
        """Order without execution_price should not crash."""
        order = {
            "action": "BUY",
            "execution_price": None,
            "filled_quantity": 0.15,
            "status": "PENDING",
        }
        formatter = OrderFormatter(order)
        assert formatter.notional_value is None
        assert formatter.is_dividend_reinvestment is False
