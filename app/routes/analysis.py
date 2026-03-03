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

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/stocks/{ticker}/analysis")
async def stock_analysis(
    ticker: str,
    refresh: bool = Query(False, description="Force fresh analysis bypassing cache"),
    agents: str | None = Query(None, description="Comma-separated agent subset, e.g. 'technical,sentiment'"),
):
    """Full multi-agent stock analysis with consensus report."""
    agent_list = [a.strip() for a in agents.split(",")] if agents else None
    return await get_stock_analysis(ticker, refresh=refresh, agents=agent_list)


@router.get("/stocks/{ticker}/analysis/technical")
async def stock_analysis_technical(
    ticker: str,
    refresh: bool = Query(False),
):
    """Technical analysis only (single agent)."""
    return await get_stock_analysis(ticker, refresh=refresh, agents=["technical"])


@router.get("/stocks/{ticker}/analysis/risk")
async def stock_analysis_risk(
    ticker: str,
    refresh: bool = Query(False),
):
    """Per-stock risk analysis only (single agent)."""
    return await get_stock_analysis(ticker, refresh=refresh, agents=["risk"])


@router.get("/portfolio/risk")
async def portfolio_risk(
    refresh: bool = Query(False, description="Force fresh risk computation"),
):
    """Portfolio-wide risk analysis (VaR, concentration, correlation)."""
    return await get_portfolio_risk(refresh=refresh)
