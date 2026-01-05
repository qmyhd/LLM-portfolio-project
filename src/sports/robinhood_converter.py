"""
Robinhood Odds Converter

Converts Robinhood Event Contract prices to American odds.
"""

from dataclasses import dataclass
from typing import Optional, Literal
from .odds_utils import decimal_to_american


@dataclass
class RHOutput:
    effective_price: float
    implied_prob: float
    decimal: float
    american: float


def convert_rh_odds(
    price: float, position: Literal["YES", "NO"], fee_per_contract: float = 0.01
) -> Optional[RHOutput]:
    """
    Convert Robinhood Event Contract price to standard odds.

    Args:
        price: Contract price (0.01 - 0.99)
        position: 'YES' or 'NO' (currently unused as price is usually for the specific side)
        fee_per_contract: Fee per contract (default 0.01)

    Returns:
        RHOutput object or None if invalid
    """
    try:
        price = float(price)
        fee_per_contract = float(fee_per_contract)
    except (ValueError, TypeError):
        return None

    if price <= 0 or price >= 1:
        return None

    # Effective price is the cost to win $1
    effective_price = price + fee_per_contract

    if effective_price >= 1:
        # If cost >= payout, it's a guaranteed loss (negative infinity odds)
        # We'll return None or handle gracefully.
        return None

    implied_prob = effective_price / 1.0

    if implied_prob <= 0:
        return None

    decimal = 1 / implied_prob
    american = decimal_to_american(decimal)

    if american is None:
        return None

    return RHOutput(
        effective_price=effective_price,
        implied_prob=implied_prob,
        decimal=decimal,
        american=american,
    )
