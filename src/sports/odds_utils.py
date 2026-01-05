"""
Odds Utility Module

Pure functions for converting between American odds, Decimal odds, and Implied Probabilities.
"""

from typing import Optional, Union


def american_to_decimal(american: float) -> Optional[float]:
    """
    Convert American odds to Decimal odds.

    Args:
        american: American odds (e.g., -110, +150)

    Returns:
        Decimal odds (e.g., 1.909, 2.50) or None if invalid
    """
    try:
        american = float(american)
    except (ValueError, TypeError):
        return None

    if american == 0 or (american > -100 and american < 100):
        # American odds cannot be between -100 and 100 (excluding 0 which is also invalid)
        return None

    if american > 0:
        return 1 + (american / 100)
    else:
        return 1 + (100 / abs(american))


def decimal_to_american(decimal: float) -> Optional[float]:
    """
    Convert Decimal odds to American odds.

    Args:
        decimal: Decimal odds (e.g., 1.91, 2.50)

    Returns:
        American odds (e.g., -110, +150) or None if invalid
    """
    try:
        decimal = float(decimal)
    except (ValueError, TypeError):
        return None

    if decimal <= 1:
        return None

    if decimal >= 2:
        return (decimal - 1) * 100
    else:
        return -100 / (decimal - 1)


def decimal_to_implied_prob(decimal: float) -> Optional[float]:
    """
    Convert Decimal odds to Implied Probability.

    Args:
        decimal: Decimal odds

    Returns:
        Implied probability (0.0 to 1.0) or None if invalid
    """
    try:
        decimal = float(decimal)
    except (ValueError, TypeError):
        return None

    if decimal <= 0:
        return None

    return 1 / decimal


def american_to_implied_prob(american: float) -> Optional[float]:
    """
    Convert American odds to Implied Probability.

    Args:
        american: American odds

    Returns:
        Implied probability (0.0 to 1.0) or None if invalid
    """
    decimal = american_to_decimal(american)
    if decimal is None:
        return None
    return decimal_to_implied_prob(decimal)
