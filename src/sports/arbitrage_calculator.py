"""
Arbitrage Calculator Module

Handles the core mathematics for sports betting arbitrage, including:
- Basic arbitrage calculation
- Odds boosts
- Stake limits
- Bias adjustments
- Profit boost hedging
"""

from dataclasses import dataclass
from typing import Optional, Tuple
from .odds_utils import (
    american_to_decimal,
    decimal_to_implied_prob,
    decimal_to_american,
)


@dataclass
class HedgeResult:
    """Result from profit boost hedge calculation."""

    # Inputs
    odds1_american: float
    stake1: float
    odds2_american: float
    boost_pct: float
    hedge_pct: float

    # Calculated Odds
    odds1_decimal_raw: float
    odds1_decimal_boosted: float
    odds2_decimal: float
    effective_american1: str

    # Stakes
    optimal_stake2: float  # Full hedge amount
    actual_stake2: float  # After applying hedge_pct
    total_stake: float

    # Payouts
    payout1: float  # If bet 1 wins
    payout2: float  # If bet 2 wins

    # Profits
    profit_if_1_wins: float
    profit_if_2_wins: float
    guaranteed_profit: float
    best_profit: float
    roi_pct: float


def calculate_hedge(
    odds1: float,
    stake1: float,
    odds2: float,
    boost_pct: float = 0.0,
    hedge_pct: float = 100.0,
) -> Optional[HedgeResult]:
    """
    Calculate optimal hedge for a profit boost.

    This is the primary use case: You have a boosted bet with a fixed stake,
    and want to calculate how much to hedge on the opposite side.

    Args:
        odds1: American odds for the boosted bet
        stake1: Fixed stake on the boosted bet (e.g., max $10)
        odds2: American odds for the hedge bet
        boost_pct: Boost percentage (e.g., 50 for a 50% profit boost)
        hedge_pct: How much of the optimal hedge to place (100 = full hedge)

    Returns:
        HedgeResult with all calculated values, or None if invalid inputs

    Example:
        +280 boosted by 50% with $10 stake, hedge at -280:
        >>> result = calculate_hedge(280, 10, -280, boost_pct=50, hedge_pct=100)
        >>> print(f"Hedge: ${result.actual_stake2:.2f}, Profit: ${result.guaranteed_profit:.2f}")
        Hedge: $38.32, Profit: $3.68
    """
    # 1. Convert to decimal odds
    dec1_raw = american_to_decimal(odds1)
    dec2 = american_to_decimal(odds2)

    if dec1_raw is None or dec2 is None:
        return None

    if stake1 <= 0:
        return None

    # 2. Apply profit boost
    # Profit boost formula: boosted_decimal = 1 + (decimal - 1) * (1 + boost_pct/100)
    if boost_pct > 0:
        dec1_boosted = 1 + (dec1_raw - 1) * (1 + boost_pct / 100)
    else:
        dec1_boosted = dec1_raw

    # 3. Calculate payout if bet 1 wins
    payout1 = stake1 * dec1_boosted

    # 4. Calculate optimal hedge (makes both outcomes equal)
    # If bet1 wins: profit = payout1 - stake1 - stake2
    # If bet2 wins: profit = stake2 * dec2 - stake1 - stake2 = stake2 * (dec2 - 1) - stake1
    # Setting equal: payout1 - stake1 - stake2 = stake2 * (dec2 - 1) - stake1
    # payout1 - stake2 = stake2 * dec2 - stake2
    # payout1 = stake2 * dec2
    # stake2 = payout1 / dec2
    optimal_stake2 = payout1 / dec2

    # 5. Apply hedge percentage
    actual_stake2 = optimal_stake2 * (hedge_pct / 100)

    # 6. Calculate outcomes
    total_stake = stake1 + actual_stake2
    payout2 = actual_stake2 * dec2

    profit_if_1_wins = payout1 - total_stake
    profit_if_2_wins = payout2 - total_stake

    guaranteed_profit = min(profit_if_1_wins, profit_if_2_wins)
    best_profit = max(profit_if_1_wins, profit_if_2_wins)
    roi_pct = (guaranteed_profit / total_stake) * 100 if total_stake > 0 else 0

    # 7. Format effective odds (handle both positive and negative)
    eff_odds1_val = decimal_to_american(dec1_boosted)
    if eff_odds1_val is None:
        eff_odds1_str = "N/A"
    elif eff_odds1_val > 0:
        eff_odds1_str = f"+{round(eff_odds1_val)}"
    else:
        eff_odds1_str = str(round(eff_odds1_val))

    return HedgeResult(
        odds1_american=odds1,
        stake1=stake1,
        odds2_american=odds2,
        boost_pct=boost_pct,
        hedge_pct=hedge_pct,
        odds1_decimal_raw=dec1_raw,
        odds1_decimal_boosted=dec1_boosted,
        odds2_decimal=dec2,
        effective_american1=eff_odds1_str,
        optimal_stake2=optimal_stake2,
        actual_stake2=actual_stake2,
        total_stake=total_stake,
        payout1=payout1,
        payout2=payout2,
        profit_if_1_wins=profit_if_1_wins,
        profit_if_2_wins=profit_if_2_wins,
        guaranteed_profit=guaranteed_profit,
        best_profit=best_profit,
        roi_pct=roi_pct,
    )


@dataclass
class ArbResult:
    # Inputs
    odds1_american: float
    odds2_american: float
    total_stake: float
    boosts1: float
    boosts2: float

    # Calculated Odds
    odds1_decimal: float
    odds2_decimal: float
    implied_prob1: float  # 0-1
    implied_prob2: float  # 0-1
    effective_american1: str
    effective_american2: str

    # Stakes & Payouts
    stake1: float
    stake2: float
    payout1: float
    payout2: float

    # Outcomes
    profit1: float
    profit2: float
    roi1: float
    roi2: float

    # Metrics
    has_arb: bool
    arb_pct: float  # Sum of implied probs (e.g. 1.05 or 0.95)
    edge_pct: float  # (1 - arb_pct) * 100
    guaranteed_profit: float  # min(profit1, profit2)


def calculate_arbitrage(
    odds1: float,
    odds2: float,
    total_stake: float,
    is_boosted1: bool = False,
    is_boosted2: bool = False,
    boost_pct1: float = 0.0,
    boost_pct2: float = 0.0,
    max_stake1: Optional[float] = None,
    max_stake2: Optional[float] = None,
    bias_to_bet1: float = 50.0,
) -> Optional[ArbResult]:
    """
    Calculate arbitrage opportunities with boosts, limits, and bias.

    Args:
        odds1: American odds for outcome 1
        odds2: American odds for outcome 2
        total_stake: Total budget
        is_boosted1: Whether outcome 1 is boosted
        is_boosted2: Whether outcome 2 is boosted
        boost_pct1: Boost percentage for outcome 1 (e.g., 30 for +30%)
        boost_pct2: Boost percentage for outcome 2
        max_stake1: Maximum stake for outcome 1
        max_stake2: Maximum stake for outcome 2
        bias_to_bet1: Bias towards Bet 1 (0-100). 50 is balanced. >50 favors 1, <50 favors 2.

    Returns:
        ArbResult object or None if inputs are invalid
    """
    # 1. Convert to Decimal
    dec1_raw = american_to_decimal(odds1)
    dec2_raw = american_to_decimal(odds2)

    if dec1_raw is None or dec2_raw is None:
        return None

    # 2. Apply Boosts
    # Effective decimal odds used for calculation
    dec1 = dec1_raw
    dec2 = dec2_raw

    actual_boost1 = boost_pct1 if is_boosted1 else 0.0
    actual_boost2 = boost_pct2 if is_boosted2 else 0.0

    if is_boosted1:
        # Profit Boost: (Decimal - 1) * (1 + boost) + 1
        dec1 = 1 + (dec1 - 1) * (1 + boost_pct1 / 100)
    if is_boosted2:
        dec2 = 1 + (dec2 - 1) * (1 + boost_pct2 / 100)

    # 3. Calculate Implied Probabilities & Arb %
    prob1 = decimal_to_implied_prob(dec1)
    prob2 = decimal_to_implied_prob(dec2)

    if prob1 is None or prob2 is None:
        return None

    arb_pct = prob1 + prob2
    has_arb = arb_pct < 1.0
    edge_pct = (1 - arb_pct) * 100

    # 4. Calculate Balanced Stakes (Zero Bias)
    base_stake1 = (total_stake * dec2) / (dec1 + dec2)

    # 5. Apply Bias
    target_stake1 = base_stake1

    if bias_to_bet1 > 50:
        # Favor 1: Interpolate between base_stake1 and total_stake
        factor = (bias_to_bet1 - 50) / 50
        target_stake1 = base_stake1 + (total_stake - base_stake1) * factor
    elif bias_to_bet1 < 50:
        # Favor 2: Interpolate between base_stake1 and 0
        factor = (50 - bias_to_bet1) / 50
        target_stake1 = base_stake1 - base_stake1 * factor

    target_stake2 = total_stake - target_stake1

    # 6. Apply Max Stake Limits
    final_stake1 = target_stake1
    final_stake2 = target_stake2

    if max_stake1 is not None and final_stake1 > max_stake1:
        final_stake1 = max_stake1
        final_stake2 = total_stake - final_stake1

    if max_stake2 is not None and final_stake2 > max_stake2:
        final_stake2 = max_stake2
        final_stake1 = total_stake - final_stake2

    # Re-check stake 1 (if stake 2 adjustment pushed it over)
    if max_stake1 is not None and final_stake1 > max_stake1:
        final_stake1 = max_stake1
        # Note: If both capped, total_stake might not be reached.
        # We accept this edge case.

    # 7. Calculate Outcomes
    payout1 = final_stake1 * dec1
    payout2 = final_stake2 * dec2

    actual_total_stake = final_stake1 + final_stake2

    profit1 = payout1 - actual_total_stake
    profit2 = payout2 - actual_total_stake

    roi1 = (profit1 / actual_total_stake) * 100 if actual_total_stake > 0 else 0
    roi2 = (profit2 / actual_total_stake) * 100 if actual_total_stake > 0 else 0

    guaranteed_profit = min(profit1, profit2)

    # Calculate effective American odds strings
    eff_odds1_val = decimal_to_american(dec1)
    eff_odds2_val = decimal_to_american(dec2)

    def fmt_odds(o):
        if o is None:
            return "N/A"
        return f"+{round(o)}" if o > 0 else str(round(o))

    eff_odds1_str = fmt_odds(eff_odds1_val)
    eff_odds2_str = fmt_odds(eff_odds2_val)

    return ArbResult(
        odds1_american=odds1,
        odds2_american=odds2,
        total_stake=actual_total_stake,
        boosts1=actual_boost1,
        boosts2=actual_boost2,
        odds1_decimal=dec1,
        odds2_decimal=dec2,
        implied_prob1=prob1,
        implied_prob2=prob2,
        effective_american1=eff_odds1_str,
        effective_american2=eff_odds2_str,
        stake1=final_stake1,
        stake2=final_stake2,
        payout1=payout1,
        payout2=payout2,
        profit1=profit1,
        profit2=profit2,
        roi1=roi1,
        roi2=roi2,
        has_arb=has_arb,
        arb_pct=arb_pct,
        edge_pct=edge_pct,
        guaranteed_profit=guaranteed_profit,
    )
