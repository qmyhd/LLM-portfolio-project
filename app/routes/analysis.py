"""API routes for multi-agent stock analysis system.

Routes:
    GET /stocks/{ticker}/analysis           → ConsensusReport
    GET /stocks/{ticker}/analysis/technical  → AnalystSignal (technical only)
    GET /stocks/{ticker}/analysis/risk       → AnalystSignal (per-stock risk)
    GET /portfolio/risk                      → PortfolioRiskReport
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from src.analysis.orchestrator import get_portfolio_risk, get_stock_analysis
from src.bucket import BucketQuery, validate_bucket

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stocks/{ticker}/analysis")
async def stock_analysis(
    ticker: str,
    refresh: bool = Query(False, description="Force fresh analysis bypassing cache"),
    agents: str | None = Query(None, description="Comma-separated agent subset, e.g. 'technical,sentiment'"),
    bucket: str | None = BucketQuery,
):
    """Full multi-agent stock analysis with consensus report.

    Pass ``?bucket=<name>`` to scope the position context and portfolio
    value fed to the risk agent. Each bucket has its own cache entry.
    """
    agent_list = [a.strip() for a in agents.split(",")] if agents else None
    return await get_stock_analysis(
        ticker,
        refresh=refresh,
        agents=agent_list,
        bucket=validate_bucket(bucket),
    )


@router.get("/stocks/{ticker}/analysis/technical")
async def stock_analysis_technical(
    ticker: str,
    refresh: bool = Query(False),
    bucket: str | None = BucketQuery,
):
    """Technical analysis only (single agent). Technical signals are
    stock-wide but the cache is bucket-keyed for consistency with the
    full-analysis route."""
    return await get_stock_analysis(
        ticker,
        refresh=refresh,
        agents=["technical"],
        bucket=validate_bucket(bucket),
    )


@router.get("/stocks/{ticker}/analysis/risk")
async def stock_analysis_risk(
    ticker: str,
    refresh: bool = Query(False),
    bucket: str | None = BucketQuery,
):
    """Per-stock risk analysis only. Bucket scopes the position-sizing
    inputs (current holdings + portfolio value)."""
    return await get_stock_analysis(
        ticker,
        refresh=refresh,
        agents=["risk"],
        bucket=validate_bucket(bucket),
    )


@router.get("/portfolio/risk")
async def portfolio_risk(
    refresh: bool = Query(False, description="Force fresh risk computation"),
    bucket: str | None = BucketQuery,
):
    """Portfolio-wide risk analysis (VaR, concentration, correlation).

    Pass ``?bucket=<name>`` to scope risk to a single strategy bucket.
    Each bucket has its own cache entry.
    """
    return await get_portfolio_risk(refresh=refresh, bucket=validate_bucket(bucket))
