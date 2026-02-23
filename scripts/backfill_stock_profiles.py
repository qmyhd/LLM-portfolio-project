#!/usr/bin/env python3
"""
Stock Profile Backfill Script

Populates stock_profile_current and stock_profile_history tables by joining:
- Supabase ohlcv_daily: Price metrics (returns, volatility)
- Supabase positions/orders: Trading activity metrics
- Supabase discord_parsed_ideas: Sentiment and mention metrics

Usage:
    python scripts/backfill_stock_profiles.py --current          # Refresh current only
    python scripts/backfill_stock_profiles.py --history          # Append to history
    python scripts/backfill_stock_profiles.py --full             # Both current + history
    python scripts/backfill_stock_profiles.py --ticker AAPL      # Single ticker
    python scripts/backfill_stock_profiles.py --dry-run          # Preview without writing

Environment:
    Requires Supabase credentials configured.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

from src.db import execute_sql, get_connection
from src.price_service import get_ohlcv, is_available as ohlcv_available
from src.retry_utils import hardened_retry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATA FETCHERS
# ============================================================================


def get_all_tracked_tickers() -> list[str]:
    """Get all tickers that have positions, orders, or parsed ideas."""
    query = """
    SELECT DISTINCT ticker FROM (
        SELECT DISTINCT symbol AS ticker FROM positions WHERE symbol IS NOT NULL
        UNION
        SELECT DISTINCT symbol AS ticker FROM orders WHERE symbol IS NOT NULL
        UNION
        SELECT DISTINCT primary_symbol AS ticker FROM discord_parsed_ideas 
        WHERE primary_symbol IS NOT NULL AND primary_symbol != ''
    ) AS all_tickers
    ORDER BY ticker
    """
    rows = execute_sql(query, fetch_results=True)
    return [row[0] for row in rows if row[0]]


def get_position_metrics(ticker: str) -> dict[str, Any]:
    """Get position metrics for a ticker from positions table."""
    query = """
    SELECT 
        SUM(quantity) AS current_qty,
        SUM(equity) AS current_value,
        AVG(average_buy_price) AS avg_buy_price,
        SUM(open_pnl) AS unrealized_pnl,
        AVG(open_pnl_percent) AS unrealized_pnl_pct
    FROM positions
    WHERE symbol = :ticker
    """
    rows = execute_sql(query, params={"ticker": ticker}, fetch_results=True)

    if rows and rows[0][0] is not None:
        row = rows[0]
        return {
            "current_position_qty": float(row[0]) if row[0] else None,
            "current_position_value": float(row[1]) if row[1] else None,
            "avg_buy_price": float(row[2]) if row[2] else None,
            "unrealized_pnl": float(row[3]) if row[3] else None,
            "unrealized_pnl_pct": float(row[4]) if row[4] else None,
        }
    return {}


def get_order_metrics(ticker: str) -> dict[str, Any]:
    """Get order/trading activity metrics for a ticker."""
    query = """
    SELECT 
        COUNT(*) AS total_orders,
        COUNT(*) FILTER (WHERE action = 'BUY') AS buy_orders,
        COUNT(*) FILTER (WHERE action = 'SELL') AS sell_orders,
        AVG(total_quantity) AS avg_order_size,
        MIN(DATE(time_executed)) AS first_trade,
        MAX(DATE(time_executed)) AS last_trade
    FROM orders
    WHERE symbol = :ticker AND status = 'executed'
    """
    rows = execute_sql(query, params={"ticker": ticker}, fetch_results=True)

    if rows and rows[0][0]:
        row = rows[0]
        return {
            "total_orders_count": int(row[0]) if row[0] else 0,
            "buy_orders_count": int(row[1]) if row[1] else 0,
            "sell_orders_count": int(row[2]) if row[2] else 0,
            "avg_order_size": float(row[3]) if row[3] else None,
            "first_trade_date": row[4],
            "last_trade_date": row[5],
        }
    return {
        "total_orders_count": 0,
        "buy_orders_count": 0,
        "sell_orders_count": 0,
    }


def get_sentiment_metrics(ticker: str) -> dict[str, Any]:
    """Get sentiment and mention metrics from discord_parsed_ideas."""
    now = datetime.now()
    days_30_ago = now - timedelta(days=30)
    days_7_ago = now - timedelta(days=7)

    query = """
    SELECT 
        COUNT(*) AS total_mentions,
        COUNT(*) FILTER (WHERE source_created_at >= :days_30) AS mentions_30d,
        COUNT(*) FILTER (WHERE source_created_at >= :days_7) AS mentions_7d,
        AVG(confidence) AS avg_confidence,
        
        -- Direction breakdown
        COUNT(*) FILTER (WHERE direction = 'bullish') AS bullish_count,
        COUNT(*) FILTER (WHERE direction = 'bearish') AS bearish_count,
        COUNT(*) FILTER (WHERE direction = 'neutral') AS neutral_count,
        
        -- First and last mention
        MIN(source_created_at) AS first_mentioned,
        MAX(source_created_at) AS last_mentioned,
        
        -- Label counts (using JSONB containment)
        COUNT(*) FILTER (WHERE 'TRADE_EXECUTION' = ANY(labels)) AS label_trade_exec,
        COUNT(*) FILTER (WHERE 'TRADE_PLAN' = ANY(labels)) AS label_trade_plan,
        COUNT(*) FILTER (WHERE 'TECHNICAL_ANALYSIS' = ANY(labels)) AS label_ta,
        COUNT(*) FILTER (WHERE 'OPTIONS' = ANY(labels)) AS label_options,
        COUNT(*) FILTER (WHERE 'CATALYST_NEWS' = ANY(labels)) AS label_catalyst
        
    FROM discord_parsed_ideas
    WHERE primary_symbol = :ticker
    """

    rows = execute_sql(
        query,
        params={
            "ticker": ticker,
            "days_30": days_30_ago,
            "days_7": days_7_ago,
        },
        fetch_results=True,
    )

    if rows and rows[0][0]:
        row = rows[0]
        total = int(row[0]) if row[0] else 0
        bullish = int(row[4]) if row[4] else 0
        bearish = int(row[5]) if row[5] else 0
        neutral = int(row[6]) if row[6] else 0

        # Calculate percentages
        bullish_pct = (bullish / total * 100) if total > 0 else None
        bearish_pct = (bearish / total * 100) if total > 0 else None
        neutral_pct = (neutral / total * 100) if total > 0 else None

        # Calculate sentiment score (-1 to 1) based on direction distribution
        if total > 0:
            sentiment_score = (bullish - bearish) / total
        else:
            sentiment_score = None

        return {
            "total_mention_count": total,
            "mention_count_30d": int(row[1]) if row[1] else 0,
            "mention_count_7d": int(row[2]) if row[2] else 0,
            "avg_sentiment_score": sentiment_score,
            "bullish_mention_pct": bullish_pct,
            "bearish_mention_pct": bearish_pct,
            "neutral_mention_pct": neutral_pct,
            "first_mentioned_at": row[7],
            "last_mentioned_at": row[8],
            "label_trade_execution_count": int(row[9]) if row[9] else 0,
            "label_trade_plan_count": int(row[10]) if row[10] else 0,
            "label_technical_analysis_count": int(row[11]) if row[11] else 0,
            "label_options_count": int(row[12]) if row[12] else 0,
            "label_catalyst_news_count": int(row[13]) if row[13] else 0,
        }

    return {
        "total_mention_count": 0,
        "mention_count_30d": 0,
        "mention_count_7d": 0,
    }


@hardened_retry(max_retries=2, delay=1)
def get_price_metrics(ticker: str) -> dict[str, Any]:
    """Get price metrics from Supabase ohlcv_daily."""
    if not ohlcv_available():
        logger.warning("OHLCV data not available, skipping price metrics")
        return {}

    # Get 1 year of data for calculations
    end_date = date.today()
    start_date = end_date - timedelta(days=365)

    try:
        df = get_ohlcv(ticker, start_date, end_date)

        if df.empty:
            logger.debug(f"No OHLCV data for {ticker}")
            return {}

        # Ensure sorted by date
        df = df.sort_index()

        # Latest prices
        latest_close = float(df["Close"].iloc[-1])

        # Previous close (for daily change)
        if len(df) >= 2:
            prev_close = float(df["Close"].iloc[-2])
            daily_change_pct = ((latest_close - prev_close) / prev_close) * 100
        else:
            prev_close = None
            daily_change_pct = None

        # Calculate returns (using available data)
        returns = {}
        return_periods = {
            "return_1w_pct": 5,
            "return_1m_pct": 21,
            "return_3m_pct": 63,
            "return_1y_pct": 252,
        }

        for key, days in return_periods.items():
            if len(df) > days:
                start_price = float(df["Close"].iloc[-(days + 1)])
                returns[key] = ((latest_close - start_price) / start_price) * 100
            else:
                returns[key] = None

        # Calculate volatility (annualized std dev of daily returns)
        daily_returns = df["Close"].pct_change().dropna()

        vol_30d = None
        vol_90d = None

        if len(daily_returns) >= 30:
            vol_30d = float(daily_returns.tail(30).std() * np.sqrt(252) * 100)

        if len(daily_returns) >= 90:
            vol_90d = float(daily_returns.tail(90).std() * np.sqrt(252) * 100)

        # 52-week high/low
        year_high = float(df["High"].max())
        year_low = float(df["Low"].min())

        # Average volume (30-day)
        avg_volume = None
        if len(df) >= 30:
            avg_volume = int(df["Volume"].tail(30).mean())

        return {
            "latest_close_price": latest_close,
            "previous_close_price": prev_close,
            "daily_change_pct": daily_change_pct,
            **returns,
            "volatility_30d": vol_30d,
            "volatility_90d": vol_90d,
            "year_high": year_high,
            "year_low": year_low,
            "avg_volume_30d": avg_volume,
        }

    except Exception as e:
        logger.error(f"Error fetching price metrics for {ticker}: {e}")
        return {}


# ============================================================================
# PROFILE BUILDERS
# ============================================================================


def build_stock_profile(ticker: str) -> dict[str, Any]:
    """Build complete stock profile by aggregating all metrics."""
    profile = {"ticker": ticker, "last_updated": datetime.now()}

    # Aggregate all metrics
    profile.update(get_price_metrics(ticker))
    profile.update(get_position_metrics(ticker))
    profile.update(get_order_metrics(ticker))
    profile.update(get_sentiment_metrics(ticker))

    return profile


def upsert_stock_profile_current(
    profile: dict[str, Any], dry_run: bool = False
) -> bool:
    """Upsert a stock profile into stock_profile_current table."""
    ticker = profile.get("ticker")
    if not ticker:
        return False

    if dry_run:
        logger.info(f"[DRY-RUN] Would upsert profile for {ticker}")
        return True

    # Build dynamic upsert query
    columns = list(profile.keys())
    placeholders = [f":{col}" for col in columns]
    updates = [f"{col} = EXCLUDED.{col}" for col in columns if col != "ticker"]

    query = f"""
    INSERT INTO stock_profile_current ({', '.join(columns)})
    VALUES ({', '.join(placeholders)})
    ON CONFLICT (ticker) DO UPDATE SET
        {', '.join(updates)},
        updated_at = NOW()
    """

    try:
        execute_sql(query, params=profile)
        logger.debug(f"Upserted profile for {ticker}")
        return True
    except Exception as e:
        logger.error(f"Failed to upsert profile for {ticker}: {e}")
        return False


def append_stock_profile_history(
    profile: dict[str, Any], as_of_date: date, dry_run: bool = False
) -> bool:
    """Append a profile snapshot to stock_profile_history."""
    ticker = profile.get("ticker")
    if not ticker:
        return False

    if dry_run:
        logger.info(f"[DRY-RUN] Would append history for {ticker} as of {as_of_date}")
        return True

    # Map current profile fields to history columns
    history_record = {
        "ticker": ticker,
        "as_of_date": as_of_date,
        "close_price": profile.get("latest_close_price"),
        "daily_change_pct": profile.get("daily_change_pct"),
        "return_1w_pct": profile.get("return_1w_pct"),
        "return_1m_pct": profile.get("return_1m_pct"),
        "return_3m_pct": profile.get("return_3m_pct"),
        "return_1y_pct": profile.get("return_1y_pct"),
        "volatility_30d": profile.get("volatility_30d"),
        "volatility_90d": profile.get("volatility_90d"),
        "year_high": profile.get("year_high"),
        "year_low": profile.get("year_low"),
        "avg_volume_30d": profile.get("avg_volume_30d"),
        "position_qty": profile.get("current_position_qty"),
        "position_value": profile.get("current_position_value"),
        "avg_buy_price": profile.get("avg_buy_price"),
        "unrealized_pnl": profile.get("unrealized_pnl"),
        "unrealized_pnl_pct": profile.get("unrealized_pnl_pct"),
        "total_orders_count": profile.get("total_orders_count"),
        "total_mention_count": profile.get("total_mention_count"),
        "mention_count_30d": profile.get("mention_count_30d"),
        "avg_sentiment_score": profile.get("avg_sentiment_score"),
        "bullish_mention_pct": profile.get("bullish_mention_pct"),
    }

    columns = list(history_record.keys())
    placeholders = [f":{col}" for col in columns]

    query = f"""
    INSERT INTO stock_profile_history ({', '.join(columns)})
    VALUES ({', '.join(placeholders)})
    ON CONFLICT (ticker, as_of_date) DO NOTHING
    """

    try:
        execute_sql(query, params=history_record)
        logger.debug(f"Appended history for {ticker} as of {as_of_date}")
        return True
    except Exception as e:
        logger.error(f"Failed to append history for {ticker}: {e}")
        return False


# ============================================================================
# MAIN ORCHESTRATION
# ============================================================================


def refresh_stock_profiles(
    tickers: Optional[list[str]] = None,
    update_current: bool = True,
    update_history: bool = True,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Refresh stock profiles for given tickers (or all tracked tickers).

    Args:
        tickers: List of tickers to refresh (None = all tracked)
        update_current: Whether to update stock_profile_current
        update_history: Whether to append to stock_profile_history
        dry_run: If True, don't write to database

    Returns:
        Dict with counts of successful/failed updates
    """
    if tickers is None:
        tickers = get_all_tracked_tickers()
        logger.info(f"Found {len(tickers)} tracked tickers")

    results = {
        "current_success": 0,
        "current_failed": 0,
        "history_success": 0,
        "history_failed": 0,
    }

    today = date.today()

    for ticker in tickers:
        logger.info(f"Processing {ticker}...")

        try:
            profile = build_stock_profile(ticker)

            if update_current:
                if upsert_stock_profile_current(profile, dry_run=dry_run):
                    results["current_success"] += 1
                else:
                    results["current_failed"] += 1

            if update_history:
                if append_stock_profile_history(profile, today, dry_run=dry_run):
                    results["history_success"] += 1
                else:
                    results["history_failed"] += 1

        except Exception as e:
            logger.error(f"Error processing {ticker}: {e}")
            results["current_failed"] += 1 if update_current else 0
            results["history_failed"] += 1 if update_history else 0

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Backfill stock profile tables",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--current",
        action="store_true",
        help="Refresh stock_profile_current only",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="Append to stock_profile_history only",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Update both current and history (default if no flags)",
    )
    parser.add_argument(
        "--ticker",
        type=str,
        help="Process single ticker (e.g., AAPL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to database",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Determine what to update
    update_current = (
        args.current or args.full or (not args.current and not args.history)
    )
    update_history = (
        args.history or args.full or (not args.current and not args.history)
    )

    # Get tickers
    tickers = [args.ticker.upper()] if args.ticker else None

    logger.info("=" * 60)
    logger.info("Stock Profile Backfill")
    logger.info("=" * 60)
    logger.info(f"Update current: {update_current}")
    logger.info(f"Update history: {update_history}")
    logger.info(f"Tickers: {tickers or 'ALL'}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 60)

    results = refresh_stock_profiles(
        tickers=tickers,
        update_current=update_current,
        update_history=update_history,
        dry_run=args.dry_run,
    )

    logger.info("=" * 60)
    logger.info("Results:")
    logger.info(
        f"  Current - Success: {results['current_success']}, Failed: {results['current_failed']}"
    )
    logger.info(
        f"  History - Success: {results['history_success']}, Failed: {results['history_failed']}"
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
