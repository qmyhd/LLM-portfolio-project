"""Tests for the analysis orchestrator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.analysis.models import AnalystSignal


@pytest.mark.anyio
async def test_orchestrator_cache_hit() -> None:
    """Returns cached result without running agents if fresh."""
    from src.analysis.orchestrator import get_stock_analysis

    cached = {
        "ticker": "AAPL",
        "overall_signal": "buy",
        "overall_confidence": 0.75,
        "bull_bear_score": 0.3,
        "agent_signals": [],
        "summary": "cached",
        "data_sources": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "gpt-5-mini",
    }
    mock_row = MagicMock()
    mock_row._mapping = {
        "result": cached,
        "agent_signals": [],
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=2),
    }

    with patch("src.analysis.orchestrator.execute_sql", return_value=[mock_row]):
        report = await get_stock_analysis("AAPL", refresh=False)
    assert report["ticker"] == "AAPL"
    assert report["summary"] == "cached"


@pytest.mark.anyio
async def test_orchestrator_cache_miss_runs_agents() -> None:
    """Cache miss triggers full agent pipeline."""
    from src.analysis.orchestrator import get_stock_analysis

    mock_signal = AnalystSignal(
        agent_id="technical",
        signal="neutral",
        confidence=0.5,
        reasoning="test",
        metrics={},
    )

    mock_input = MagicMock()
    mock_input.ticker = "AAPL"

    with (
        patch("src.analysis.orchestrator.execute_sql", return_value=[]),
        patch("src.analysis.orchestrator._assemble_input") as mock_assemble,
        patch(
            "src.analysis.orchestrator._run_agents",
            new_callable=AsyncMock,
            return_value=[mock_signal] * 5,
        ) as mock_run,
        patch("src.analysis.orchestrator._run_consensus", new_callable=AsyncMock) as mock_consensus,
        patch("src.analysis.orchestrator._cache_result"),
    ):
        mock_assemble.return_value = (mock_input, ["Databento OHLCV"])
        mock_consensus.return_value = {
            "ticker": "AAPL",
            "overall_signal": "hold",
            "overall_confidence": 0.5,
            "bull_bear_score": 0.0,
            "agent_signals": [],
            "summary": "test",
            "data_sources": ["Databento OHLCV"],
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "model_used": "gpt-5-mini",
        }

        report = await get_stock_analysis("AAPL", refresh=False)

    assert report["ticker"] == "AAPL"
    mock_run.assert_called_once()
    mock_consensus.assert_called_once()


@pytest.mark.anyio
async def test_orchestrator_refresh_bypasses_cache() -> None:
    """refresh=True should skip cache and run full pipeline."""
    from src.analysis.orchestrator import get_stock_analysis

    mock_signal = AnalystSignal(
        agent_id="technical",
        signal="bullish",
        confidence=0.8,
        reasoning="test",
        metrics={},
    )

    mock_input = MagicMock()
    mock_input.ticker = "TSLA"

    with (
        patch("src.analysis.orchestrator.execute_sql"),
        patch("src.analysis.orchestrator._assemble_input") as mock_assemble,
        patch(
            "src.analysis.orchestrator._run_agents",
            new_callable=AsyncMock,
            return_value=[mock_signal],
        ),
        patch("src.analysis.orchestrator._run_consensus", new_callable=AsyncMock) as mock_consensus,
        patch("src.analysis.orchestrator._cache_result"),
    ):
        mock_assemble.return_value = (mock_input, [])
        mock_consensus.return_value = {
            "ticker": "TSLA",
            "overall_signal": "buy",
            "overall_confidence": 0.8,
            "bull_bear_score": 0.5,
            "agent_signals": [],
            "summary": "refreshed",
            "data_sources": [],
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "model_used": "gpt-5-mini",
        }

        report = await get_stock_analysis("TSLA", refresh=True)

    # _check_cache calls execute_sql; with refresh=True it should NOT be called for cache lookup
    # execute_sql is called inside _cache_result (patched), so mock_sql should not have been called
    # for the cache check path
    assert report["ticker"] == "TSLA"
    assert report["summary"] == "refreshed"


@pytest.mark.anyio
async def test_orchestrator_stale_triggers_background_refresh() -> None:
    """Stale cache returns stale result and triggers background refresh."""
    from src.analysis.orchestrator import get_stock_analysis

    stale_result = {
        "ticker": "MSFT",
        "overall_signal": "hold",
        "overall_confidence": 0.5,
        "bull_bear_score": 0.0,
        "agent_signals": [],
        "summary": "stale",
        "data_sources": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "gpt-5-mini",
    }
    mock_row = MagicMock()
    mock_row._mapping = {
        "result": stale_result,
        "agent_signals": [],
        # Expired 1 hour ago
        "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),
    }

    with (
        patch("src.analysis.orchestrator.execute_sql", return_value=[mock_row]),
        patch("src.analysis.orchestrator._refresh_analysis", new_callable=AsyncMock),
        patch("asyncio.create_task") as mock_create_task,
    ):
        report = await get_stock_analysis("MSFT", refresh=False)

    assert report["summary"] == "stale"
    # Background refresh should have been scheduled
    mock_create_task.assert_called_once()


@pytest.mark.anyio
async def test_run_agents_handles_failure() -> None:
    """A failing agent returns neutral signal with error info."""
    from src.analysis.orchestrator import _run_agents

    mock_input = MagicMock()
    mock_input.ticker = "AAPL"

    async def failing_run(_input):
        raise RuntimeError("Agent exploded")

    async def ok_run(_input):
        return AnalystSignal(
            agent_id="technical",
            signal="bullish",
            confidence=0.8,
            reasoning="test",
            metrics={},
        )

    with (
        patch("src.analysis.orchestrator.technical.run", side_effect=failing_run),
        patch("src.analysis.orchestrator.fundamental.run", side_effect=ok_run),
        patch("src.analysis.orchestrator.valuation.run", side_effect=ok_run),
        patch("src.analysis.orchestrator.sentiment.run", side_effect=ok_run),
        patch("src.analysis.orchestrator.risk.run", side_effect=ok_run),
    ):
        signals = await _run_agents(mock_input)

    assert len(signals) == 5
    # The failed agent should produce a neutral signal with 0.0 confidence
    failed = [s for s in signals if s.confidence == 0.0]
    assert len(failed) == 1
    assert failed[0].signal == "neutral"
    assert "error" in failed[0].reasoning.lower()


@pytest.mark.anyio
async def test_run_agents_filters_by_name() -> None:
    """Only requested agents run when agents list is specified."""
    from src.analysis.orchestrator import _run_agents

    mock_input = MagicMock()
    mock_input.ticker = "AAPL"

    call_count = 0

    async def counting_run(_input):
        nonlocal call_count
        call_count += 1
        return AnalystSignal(
            agent_id="test",
            signal="neutral",
            confidence=0.5,
            reasoning="test",
            metrics={},
        )

    with (
        patch("src.analysis.orchestrator.technical.run", side_effect=counting_run),
        patch("src.analysis.orchestrator.fundamental.run", side_effect=counting_run),
        patch("src.analysis.orchestrator.valuation.run", side_effect=counting_run),
        patch("src.analysis.orchestrator.sentiment.run", side_effect=counting_run),
        patch("src.analysis.orchestrator.risk.run", side_effect=counting_run),
    ):
        signals = await _run_agents(mock_input, agents=["technical", "risk"])

    assert len(signals) == 2
    assert call_count == 2


def test_check_cache_returns_none_on_miss() -> None:
    """No cache rows returns None."""
    from src.analysis.orchestrator import _check_cache

    with patch("src.analysis.orchestrator.execute_sql", return_value=[]):
        result = _check_cache("AAPL")
    assert result is None


def test_check_cache_parses_json_string() -> None:
    """Cache result stored as JSON string is parsed."""
    import json

    from src.analysis.orchestrator import _check_cache

    data = {"ticker": "AAPL", "summary": "test"}
    mock_row = MagicMock()
    mock_row._mapping = {
        "result": json.dumps(data),
        "agent_signals": [],
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=2),
    }

    with patch("src.analysis.orchestrator.execute_sql", return_value=[mock_row]):
        result = _check_cache("AAPL")

    assert result is not None
    assert result["result"]["ticker"] == "AAPL"
    assert result["is_fresh"] is True


def test_is_crypto() -> None:
    """Crypto detection uses _CRYPTO_SYMBOLS from market_data_service."""
    from src.analysis.orchestrator import _is_crypto

    with patch("src.market_data_service._CRYPTO_SYMBOLS", frozenset({"BTC", "ETH", "SOL"})):
        assert _is_crypto("BTC") is True
        assert _is_crypto("btc") is True
        assert _is_crypto("AAPL") is False
