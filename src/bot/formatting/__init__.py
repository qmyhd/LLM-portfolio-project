"""
Formatting helpers for Discord bot commands.

This module provides deterministic formatting functions for
consistent display of financial data in Discord embeds.
"""

from .orders_view import (
    format_money,
    format_pct,
    format_qty,
    normalize_side,
    best_price,
    safe_status,
    OrderFormatter,
)

__all__ = [
    "format_money",
    "format_pct",
    "format_qty",
    "normalize_side",
    "best_price",
    "safe_status",
    "OrderFormatter",
]
