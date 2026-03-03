"""Analysis orchestrator — data assembly, caching, and agent dispatch.

Coordinates the multi-agent analysis pipeline:
1. Check cache -> return if fresh
2. Assemble AnalysisInput from multiple data sources
3. Run 5 agents in parallel via asyncio.gather
4. Run consensus aggregator
5. Cache and return result

Stale-while-revalidate: if cache exists but expired, return stale immediately
and trigger background refresh via asyncio.create_task().
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from src.analysis import technical, fundamental, valuation, sentiment, risk
from src.analysis.consensus import run as consensus_run
from src.analysis.models import (
    AnalysisInput,
    AnalystSignal,
    IdeaData,
    NewsItem,
    OHLCVBar,
    PortfolioRiskReport,
    PositionData,
)
from src.analysis.risk import compute_portfolio_risk
from src.db import execute_sql

logger = logging.getLogger(__name__)

# TTL configuration
EQUITY_TTL_HOURS = 4
CRYPTO_TTL_HOURS = 1
PORTFOLIO_RISK_TTL_HOURS = 2


def _is_crypto(ticker: str) -> bool:
    """Check if ticker is a cryptocurrency."""
    try:
        from src.market_data_service import _CRYPTO_SYMBOLS

        return ticker.upper() in _CRYPTO_SYMBOLS
    except ImportError:
        return False


def _check_cache(ticker: str, analysis_type: str = "full") -> dict | None:
    """Check stock_analysis_cache for fresh result.

    Returns dict with keys ``result`` (parsed) and ``is_fresh`` (bool),
    or *None* if no cache row exists.
    """
    rows = execute_sql(
        """
        SELECT result, agent_signals, expires_at
        FROM stock_analysis_cache
        WHERE ticker = :ticker AND analysis_type = :analysis_type
        ORDER BY computed_at DESC
        LIMIT 1
        """,
        params={"ticker": ticker.upper(), "analysis_type": analysis_type},
        fetch_results=True,
    )
    if not rows:
        return None

    row = rows[0]
    mapping = row._mapping if hasattr(row, "_mapping") else row
    result = mapping["result"]
    expires_at = mapping["expires_at"]

    # Ensure timezone-aware comparison
    now = datetime.now(tz=timezone.utc)
    if hasattr(expires_at, "tzinfo") and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    is_fresh = now < expires_at

    if isinstance(result, str):
        result = json.loads(result)

    return {"result": result, "is_fresh": is_fresh}


def _assemble_input(ticker: str) -> tuple[AnalysisInput, list[str]]:
    """Assemble AnalysisInput from multiple data sources.

    Returns ``(AnalysisInput, data_sources_list)``.
    """
    data_sources: list[str] = []
    ohlcv_bars: list[OHLCVBar] = []
    fundamentals_data: dict | None = None
    position_data: PositionData | None = None
    ideas_list: list[IdeaData] = []
    news_list: list[NewsItem] = []
    portfolio_value = 0.0

    ticker_upper = ticker.upper()

    # 1. OHLCV data
    if not _is_crypto(ticker_upper):
        try:
            from src.price_service import get_ohlcv

            df = get_ohlcv(ticker_upper)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    ohlcv_bars.append(
                        OHLCVBar(
                            date=str(row["date"]),
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row["volume"]),
                        )
                    )
                data_sources.append(f"Databento OHLCV ({len(ohlcv_bars)} days)")
        except Exception:
            logger.warning("Failed to fetch OHLCV for %s", ticker_upper, exc_info=True)

    # 2. Fundamentals
    try:
        from src.openbb_service import get_fundamentals

        fundamentals_data = get_fundamentals(ticker_upper)
        if fundamentals_data:
            data_sources.append("OpenBB/FMP fundamentals")
    except Exception:
        logger.warning("Failed to fetch fundamentals for %s", ticker_upper, exc_info=True)

    # 3. News
    try:
        from src.openbb_service import get_company_news

        raw_news = get_company_news(ticker_upper, limit=20)
        for item in raw_news:
            news_list.append(
                NewsItem(
                    title=item.get("title", ""),
                    date=item.get("date", ""),
                    text=item.get("text", ""),
                    source=item.get("source", ""),
                    sentiment_score=item.get("sentiment_score"),
                )
            )
        if news_list:
            data_sources.append(f"OpenBB/FMP news ({len(news_list)} articles)")
    except Exception:
        logger.warning("Failed to fetch news for %s", ticker_upper, exc_info=True)

    # 4. Discord parsed ideas
    try:
        idea_rows = execute_sql(
            """
            SELECT direction, confidence, labels, idea_text, created_at, author
            FROM discord_parsed_ideas
            WHERE UPPER(ticker) = :ticker
            AND created_at > NOW() - INTERVAL '30 days'
            ORDER BY created_at DESC
            LIMIT 50
            """,
            params={"ticker": ticker_upper},
            fetch_results=True,
        )
        for row in idea_rows:
            m = row._mapping if hasattr(row, "_mapping") else row
            ideas_list.append(
                IdeaData(
                    direction=m.get("direction", "neutral") or "neutral",
                    confidence=float(m.get("confidence", 0.5) or 0.5),
                    labels=m.get("labels", []) or [],
                    idea_text=m.get("idea_text", "") or "",
                    created_at=str(m.get("created_at", "")),
                    author=m.get("author", "") or "",
                )
            )
        if ideas_list:
            data_sources.append(f"Discord NLP ({len(ideas_list)} ideas)")
    except Exception:
        logger.warning("Failed to fetch ideas for %s", ticker_upper, exc_info=True)

    # 5. Position data
    try:
        pos_rows = execute_sql(
            """
            SELECT quantity, avg_cost, price as current_price, market_value,
                   unrealized_pnl, unrealized_pnl_pct
            FROM positions
            WHERE UPPER(symbol) = :ticker
            LIMIT 1
            """,
            params={"ticker": ticker_upper},
            fetch_results=True,
        )
        if pos_rows:
            m = pos_rows[0]._mapping if hasattr(pos_rows[0], "_mapping") else pos_rows[0]
            position_data = PositionData(
                quantity=float(m.get("quantity", 0) or 0),
                avg_cost=float(m.get("avg_cost", 0) or 0),
                current_price=float(m.get("current_price", 0) or 0),
                market_value=float(m.get("market_value", 0) or 0),
                unrealized_pnl=float(m.get("unrealized_pnl", 0) or 0),
                unrealized_pnl_pct=float(m.get("unrealized_pnl_pct", 0) or 0),
            )
            data_sources.append(f"Portfolio positions ({m.get('quantity', 0)} shares)")
    except Exception:
        logger.warning("Failed to fetch position for %s", ticker_upper, exc_info=True)

    # 6. Portfolio value
    try:
        bal_rows = execute_sql(
            "SELECT SUM(total_value) as total FROM account_balances",
            fetch_results=True,
        )
        if bal_rows:
            m = bal_rows[0]._mapping if hasattr(bal_rows[0], "_mapping") else bal_rows[0]
            portfolio_value = float(m.get("total", 0) or 0)
    except Exception:
        logger.warning("Failed to fetch portfolio value", exc_info=True)

    analysis_input = AnalysisInput(
        ticker=ticker_upper,
        ohlcv=ohlcv_bars,
        fundamentals=fundamentals_data,
        position=position_data,
        ideas=ideas_list,
        news=news_list,
        portfolio_value=portfolio_value,
    )

    return analysis_input, data_sources


async def _run_agents(
    input_data: AnalysisInput,
    agents: list[str] | None = None,
) -> list[AnalystSignal]:
    """Run analysis agents in parallel.  Returns list of AnalystSignal.

    Each agent is wrapped in try/except -- if one fails, it returns a
    neutral signal with error info in reasoning.
    """
    agent_map = {
        "technical": technical.run,
        "fundamental": fundamental.run,
        "valuation": valuation.run,
        "sentiment": sentiment.run,
        "risk": risk.run,
    }

    if agents:
        agent_map = {k: v for k, v in agent_map.items() if k in agents}

    async def safe_run(name: str, fn):
        try:
            return await fn(input_data)
        except Exception:
            logger.warning("Agent %s failed for %s", name, input_data.ticker, exc_info=True)
            return AnalystSignal(
                agent_id=name,
                signal="neutral",
                confidence=0.0,
                reasoning=f"Agent {name} encountered an error",
                metrics={"error": True},
            )

    tasks = [safe_run(name, fn) for name, fn in agent_map.items()]
    results = await asyncio.gather(*tasks)
    return list(results)


async def _run_consensus(
    ticker: str,
    signals: list[AnalystSignal],
    data_sources: list[str],
) -> dict:
    """Run consensus aggregator and return serialized report."""
    report = await consensus_run(ticker, signals, data_sources)
    return report.model_dump(mode="json")


def _cache_result(
    ticker: str,
    analysis_type: str,
    result: dict,
    agent_signals: list[dict],
    model_used: str,
    data_sources: list[str],
) -> None:
    """Upsert result into stock_analysis_cache."""
    ttl_hours = CRYPTO_TTL_HOURS if _is_crypto(ticker) else EQUITY_TTL_HOURS
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=ttl_hours)

    execute_sql(
        """
        INSERT INTO stock_analysis_cache
            (ticker, analysis_type, result, agent_signals, model_used, data_sources, computed_at, expires_at)
        VALUES
            (:ticker, :analysis_type, :result, :agent_signals, :model_used, :data_sources, NOW(), :expires_at)
        ON CONFLICT (ticker, analysis_type) DO UPDATE SET
            result = EXCLUDED.result,
            agent_signals = EXCLUDED.agent_signals,
            model_used = EXCLUDED.model_used,
            data_sources = EXCLUDED.data_sources,
            computed_at = NOW(),
            expires_at = EXCLUDED.expires_at
        """,
        params={
            "ticker": ticker.upper(),
            "analysis_type": analysis_type,
            "result": json.dumps(result),
            "agent_signals": json.dumps(agent_signals),
            "model_used": model_used,
            "data_sources": data_sources,
            "expires_at": expires_at,
        },
    )


async def get_stock_analysis(
    ticker: str,
    refresh: bool = False,
    agents: list[str] | None = None,
) -> dict:
    """Main entry point for stock analysis.

    1. Check cache (unless refresh=True)
    2. If fresh cache -> return cached result
    3. If stale cache -> return stale, trigger background refresh
    4. If no cache -> run full pipeline

    Args:
        ticker: Stock ticker symbol
        refresh: Force fresh analysis bypassing cache
        agents: Optional list of specific agents to run
    """
    analysis_type = "full" if not agents else ",".join(sorted(agents))

    if not refresh:
        cached = _check_cache(ticker, analysis_type)
        if cached:
            if cached["is_fresh"]:
                return cached["result"]
            # Stale-while-revalidate: return stale, trigger background refresh
            asyncio.create_task(_refresh_analysis(ticker, analysis_type, agents))
            return cached["result"]

    return await _compute_analysis(ticker, analysis_type, agents)


async def _refresh_analysis(
    ticker: str,
    analysis_type: str,
    agents: list[str] | None,
) -> None:
    """Background refresh task for stale-while-revalidate."""
    try:
        await _compute_analysis(ticker, analysis_type, agents)
    except Exception:
        logger.warning("Background refresh failed for %s", ticker, exc_info=True)


async def _compute_analysis(
    ticker: str,
    analysis_type: str,
    agents: list[str] | None,
) -> dict:
    """Run the full analysis pipeline."""
    # Assemble input
    input_data, data_sources = _assemble_input(ticker)

    # Run agents
    signals = await _run_agents(input_data, agents)

    # Run consensus
    result = await _run_consensus(ticker, signals, data_sources)

    # Cache
    agent_signal_dicts = [s.model_dump(mode="json") for s in signals]
    _cache_result(
        ticker=ticker,
        analysis_type=analysis_type,
        result=result,
        agent_signals=agent_signal_dicts,
        model_used=result.get("model_used", "unknown"),
        data_sources=data_sources,
    )

    return result


async def get_portfolio_risk(refresh: bool = False) -> dict:
    """Compute portfolio-wide risk metrics.

    Fetches all positions, gets OHLCV for top 15 holdings by market value,
    then runs portfolio risk analysis.
    """
    # Check cache
    if not refresh:
        rows = execute_sql(
            """
            SELECT result, expires_at
            FROM portfolio_risk_cache
            WHERE portfolio_id = 'default'
            LIMIT 1
            """,
            fetch_results=True,
        )
        if rows:
            m = rows[0]._mapping if hasattr(rows[0], "_mapping") else rows[0]
            expires_at = m["expires_at"]
            now = datetime.now(tz=timezone.utc)
            if hasattr(expires_at, "tzinfo") and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now < expires_at:
                result = m["result"]
                if isinstance(result, str):
                    result = json.loads(result)
                return result

    # Fetch top 15 positions by market value
    pos_rows = execute_sql(
        """
        SELECT symbol, quantity, market_value
        FROM positions
        WHERE quantity > 0
        ORDER BY market_value DESC NULLS LAST
        LIMIT 15
        """,
        fetch_results=True,
    )

    if not pos_rows:
        empty_report = PortfolioRiskReport(
            var_95_1d=0.0,
            var_95_5d=0.0,
            concentration_hhi=0.0,
            diversification_ratio=0.0,
            correlation_matrix={},
            top_risk_contributors=[],
            sector_exposure={},
            computed_at=datetime.now(tz=timezone.utc),
            data_sources=[],
        )
        return empty_report.model_dump(mode="json")

    # Collect OHLCV returns and weights
    import numpy as np

    returns_data: dict[str, np.ndarray] = {}
    weights: dict[str, float] = {}
    sector_map: dict[str, str] = {}
    total_market_value = 0.0

    for row in pos_rows:
        m = row._mapping if hasattr(row, "_mapping") else row
        mv = float(m.get("market_value", 0) or 0)
        total_market_value += mv

    for row in pos_rows:
        m = row._mapping if hasattr(row, "_mapping") else row
        symbol = m["symbol"]
        mv = float(m.get("market_value", 0) or 0)
        weights[symbol] = mv / total_market_value if total_market_value > 0 else 0.0

        # Get OHLCV returns
        try:
            from src.price_service import get_ohlcv

            df = get_ohlcv(symbol)
            if df is not None and not df.empty and len(df) > 10:
                returns = df["close"].pct_change().dropna().values
                returns_data[symbol] = returns
        except Exception:
            logger.warning("Failed to fetch OHLCV for portfolio risk: %s", symbol, exc_info=True)

        # Get sector
        try:
            from src.market_data_service import get_company_info

            info = get_company_info(symbol)
            if info and "sector" in info:
                sector_map[symbol] = info["sector"]
            else:
                sector_map[symbol] = "Unknown"
        except Exception:
            sector_map[symbol] = "Unknown"

    # Only include tickers that have returns data
    valid_weights = {t: w for t, w in weights.items() if t in returns_data}

    # Get total portfolio value
    try:
        bal_rows = execute_sql(
            "SELECT SUM(total_value) as total FROM account_balances",
            fetch_results=True,
        )
        if bal_rows:
            bm = bal_rows[0]._mapping if hasattr(bal_rows[0], "_mapping") else bal_rows[0]
            total_value = float(bm.get("total", 0) or 0)
        else:
            total_value = total_market_value
    except Exception:
        total_value = total_market_value

    report = compute_portfolio_risk(
        returns_data=returns_data,
        weights=valid_weights,
        sector_map=sector_map,
        total_value=total_value,
    )

    result = report.model_dump(mode="json")

    # Cache result
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=PORTFOLIO_RISK_TTL_HOURS)
    execute_sql(
        """
        INSERT INTO portfolio_risk_cache (portfolio_id, result, computed_at, expires_at)
        VALUES ('default', :result, NOW(), :expires_at)
        ON CONFLICT (portfolio_id) DO UPDATE SET
            result = EXCLUDED.result,
            computed_at = NOW(),
            expires_at = EXCLUDED.expires_at
        """,
        params={
            "result": json.dumps(result),
            "expires_at": expires_at,
        },
    )

    return result
