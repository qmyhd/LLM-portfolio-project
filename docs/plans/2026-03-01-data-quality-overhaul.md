# Data Quality Overhaul — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix crypto price identity collisions, day change explosions, duplicate holdings, order display bugs, and add ideas context navigation — making the portfolio dashboard show correct, trustworthy data.

**Architecture:** Split price lookups by asset type so crypto never hits Databento equity OHLCV. Add canonical `CRYPTO_IDENTITY` dict for TradingView/yfinance symbol resolution. Add guardrails for day change % with crypto-specific 24h logic. Backend returns `tvSymbol` so frontend never guesses exchange format.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.0 / PostgreSQL (Supabase) / Next.js 14 / TypeScript / yfinance / TradingView widgets

**Design doc:** `docs/plans/2026-03-01-data-quality-overhaul-design.md`

**Ground truth (2026-03-01 6:15 PM ET):** XRP=$1.353, BTC=$65,842.71, TRUMP=$3.43, NVDA=$177.80, GOOGL=$309.20

---

## Task 1: Add CRYPTO_IDENTITY dict and update _yf_symbol()

**Files:**
- Modify: `src/market_data_service.py:37-48`
- Test: `tests/test_market_data_service.py`

**Step 1: Write failing tests for CRYPTO_IDENTITY and updated _yf_symbol**

Add to `tests/test_market_data_service.py`:

```python
class TestCryptoIdentity:
    def test_crypto_identity_has_all_crypto_symbols(self):
        from src.market_data_service import _CRYPTO_SYMBOLS, CRYPTO_IDENTITY
        for sym in _CRYPTO_SYMBOLS:
            assert sym in CRYPTO_IDENTITY, f"{sym} missing from CRYPTO_IDENTITY"

    def test_crypto_identity_has_required_keys(self):
        from src.market_data_service import CRYPTO_IDENTITY
        for sym, info in CRYPTO_IDENTITY.items():
            assert "quote_symbol" in info, f"{sym} missing quote_symbol"
            assert "tv_symbol" in info, f"{sym} missing tv_symbol"
            assert info["quote_symbol"].endswith("-USD"), f"{sym} quote_symbol should end with -USD"

    def test_yf_symbol_uses_crypto_identity(self):
        from src.market_data_service import _yf_symbol
        assert _yf_symbol("BTC") == "BTC-USD"
        assert _yf_symbol("XRP") == "XRP-USD"
        assert _yf_symbol("TRUMP") == "TRUMP-USD"
        assert _yf_symbol("AAPL") == "AAPL"

    def test_crypto_identity_tv_symbols_have_exchange(self):
        from src.market_data_service import CRYPTO_IDENTITY
        for sym, info in CRYPTO_IDENTITY.items():
            assert ":" in info["tv_symbol"], f"{sym} tv_symbol must be EXCHANGE:SYMBOL format"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_market_data_service.py::TestCryptoIdentity -v`
Expected: FAIL — `CRYPTO_IDENTITY` not defined

**Step 3: Implement CRYPTO_IDENTITY dict**

In `src/market_data_service.py`, replace lines 37-48 with:

```python
# Known crypto tickers that need -USD suffix for yfinance
_CRYPTO_SYMBOLS = frozenset(
    {"XRP", "BTC", "ETH", "SOL", "ADA", "DOGE", "AVAX", "LINK", "DOT", "MATIC", "SHIB",
     "PEPE", "TRUMP"}
)

# Canonical identity for each crypto asset — single source of truth
# quote_symbol: yfinance-compatible symbol for price fetching
# tv_symbol: TradingView widget symbol (EXCHANGE:PAIR format)
CRYPTO_IDENTITY: dict[str, dict[str, str]] = {
    "BTC":   {"quote_symbol": "BTC-USD",   "tv_symbol": "COINBASE:BTCUSD"},
    "ETH":   {"quote_symbol": "ETH-USD",   "tv_symbol": "COINBASE:ETHUSD"},
    "SOL":   {"quote_symbol": "SOL-USD",   "tv_symbol": "COINBASE:SOLUSD"},
    "XRP":   {"quote_symbol": "XRP-USD",   "tv_symbol": "COINBASE:XRPUSD"},
    "ADA":   {"quote_symbol": "ADA-USD",   "tv_symbol": "COINBASE:ADAUSD"},
    "DOGE":  {"quote_symbol": "DOGE-USD",  "tv_symbol": "COINBASE:DOGEUSD"},
    "AVAX":  {"quote_symbol": "AVAX-USD",  "tv_symbol": "COINBASE:AVAXUSD"},
    "LINK":  {"quote_symbol": "LINK-USD",  "tv_symbol": "COINBASE:LINKUSD"},
    "DOT":   {"quote_symbol": "DOT-USD",   "tv_symbol": "COINBASE:DOTUSD"},
    "MATIC": {"quote_symbol": "MATIC-USD", "tv_symbol": "COINBASE:MATICUSD"},
    "SHIB":  {"quote_symbol": "SHIB-USD",  "tv_symbol": "COINBASE:SHIBUSD"},
    "PEPE":  {"quote_symbol": "PEPE-USD",  "tv_symbol": "CRYPTO:PEPEUSD"},
    "TRUMP": {"quote_symbol": "TRUMP-USD", "tv_symbol": "CRYPTO:TRUMPUSD"},
}


def _yf_symbol(symbol: str) -> str:
    """Normalise a portfolio symbol into a yfinance-compatible symbol."""
    identity = CRYPTO_IDENTITY.get(symbol)
    if identity:
        return identity["quote_symbol"]
    return symbol
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_market_data_service.py::TestCryptoIdentity -v`
Expected: PASS (all 4 tests)

**Step 5: Run full test suite to check for regressions**

Run: `pytest tests/ -v -m "not openai and not integration" --tb=short`
Expected: All existing tests pass

**Step 6: Commit**

```bash
git add src/market_data_service.py tests/test_market_data_service.py
git commit -m "feat: add CRYPTO_IDENTITY dict for canonical crypto symbol resolution"
```

---

## Task 2: Split price lookup by asset type in portfolio.py

**Files:**
- Modify: `app/routes/portfolio.py:246-270`
- Test: `tests/test_portfolio_price_routing.py` (new file)

**Step 1: Write failing test for crypto price routing**

Create `tests/test_portfolio_price_routing.py`:

```python
"""
Tests for crypto vs equity price routing in portfolio endpoint.

Verifies that crypto symbols are NEVER sent to Databento (ohlcv_daily)
and always routed through yfinance with -USD suffix.
"""

from unittest.mock import MagicMock, patch, call
import pytest


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from app.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c


def _mock_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


class TestCryptoPriceRouting:
    """Crypto symbols must never hit Databento; always use yfinance."""

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_crypto_excluded_from_databento(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """BTC position should not be passed to Databento batch queries."""
        # DB returns one crypto position + one equity position
        mock_sql.side_effect = [
            # positions query
            [
                _mock_row({
                    "symbol": "BTC", "quantity": 0.001, "average_cost": 50000,
                    "snaptrade_price": 65000, "raw_symbol": "BTC",
                    "account_id": "acc1", "asset_type": "Cryptocurrency",
                    "company_name": "Bitcoin",
                }),
                _mock_row({
                    "symbol": "AAPL", "quantity": 10, "average_cost": 150,
                    "snaptrade_price": 175, "raw_symbol": "AAPL",
                    "account_id": "acc1", "asset_type": "Common Stock",
                    "company_name": "Apple Inc.",
                }),
            ],
            # account_balances query
            [_mock_row({"cash": 100, "buying_power": 200})],
            # connection status query
            [_mock_row({"worst_status": "connected"})],
            # last sync query
            [_mock_row({"last_sync": "2026-03-01T18:00:00+00:00"})],
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {"AAPL": 176.0}
        mock_yf.return_value = {
            "BTC": {"price": 65842.71, "previousClose": 65000.0, "dayChange": 842.71, "dayChangePct": 1.30},
        }

        response = client.get("/portfolio")
        assert response.status_code == 200

        # Verify Databento was called with ONLY equity symbols
        latest_call_args = mock_latest.call_args
        assert "BTC" not in latest_call_args[0][0], "BTC should NOT be sent to Databento"
        assert "AAPL" in latest_call_args[0][0], "AAPL should be sent to Databento"

        prev_call_args = mock_prev.call_args
        assert "BTC" not in prev_call_args[0][0], "BTC should NOT be in prev_closes query"

        # Verify yfinance was called with BTC
        yf_call_args = mock_yf.call_args[0][0]
        assert "BTC" in yf_call_args, "BTC must be routed to yfinance"

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_crypto_gets_correct_price(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Crypto position price should come from yfinance, not Databento."""
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "XRP", "quantity": 50, "average_cost": 1.0,
                "snaptrade_price": 1.35, "raw_symbol": "XRP",
                "account_id": "acc1", "asset_type": "Cryptocurrency",
                "company_name": "XRP",
            })],
            [_mock_row({"cash": 0, "buying_power": 0})],
            [_mock_row({"worst_status": "connected"})],
            [_mock_row({"last_sync": "2026-03-01T18:00:00+00:00"})],
        ]
        mock_latest.return_value = {}  # Databento returns nothing (crypto excluded)
        mock_prev.return_value = {}
        mock_yf.return_value = {
            "XRP": {"price": 1.353, "previousClose": 1.30, "dayChange": 0.053, "dayChangePct": 4.08},
        }

        response = client.get("/portfolio")
        data = response.json()
        assert response.status_code == 200

        xrp = next(p for p in data["positions"] if p["symbol"] == "XRP")
        assert xrp["currentPrice"] == 1.35  # yfinance price rounded
        assert xrp["assetType"] == "crypto"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_portfolio_price_routing.py -v`
Expected: FAIL — BTC is being sent to Databento

**Step 3: Implement the price routing split**

In `app/routes/portfolio.py`, replace lines 246-270 with:

```python
        # ---- Phase 1B: Batch fetch prices ----
        # CRITICAL: Split by asset type to avoid crypto/equity ticker collisions.
        # Databento ohlcv_daily has equity tickers (BTC=Grayscale, ETH=Ethan Allen)
        # that collide with crypto symbols. Never send crypto to Databento.
        from src.market_data_service import get_realtime_quotes_batch, _CRYPTO_SYMBOLS

        crypto_syms = [s for s in symbols_to_fetch if s in _CRYPTO_SYMBOLS]
        equity_syms = [s for s in symbols_to_fetch if s not in _CRYPTO_SYMBOLS]

        # Databento ONLY for equities
        prices_map = get_latest_closes_batch(equity_syms) if equity_syms else {}
        prev_closes_map = get_previous_closes_batch(equity_syms) if equity_syms else {}

        # yfinance for ALL crypto + equity symbols Databento doesn't cover
        yf_quotes: dict[str, dict] = {}
        yf_needed = crypto_syms + [s for s in equity_syms if s not in prices_map]
        if yf_needed:
            try:
                yf_quotes = get_realtime_quotes_batch(yf_needed)
            except Exception as exc:
                logger.debug("yfinance batch quotes skipped: %s", exc)
```

Note: This replaces the old pattern where `get_latest_closes_batch` was called with ALL symbols, followed by a `databento_missing` list. The import of `get_realtime_quotes_batch` at line 260 is now at the top of the block instead of inside the `if`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_portfolio_price_routing.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -v -m "not openai and not integration" --tb=short`
Expected: All pass

**Step 6: Commit**

```bash
git add app/routes/portfolio.py tests/test_portfolio_price_routing.py
git commit -m "fix: route crypto symbols to yfinance, never to Databento ohlcv_daily"
```

---

## Task 3: Day change guardrails (crypto 24h + equity cap)

**Files:**
- Modify: `app/routes/portfolio.py:325-337`
- Test: `tests/test_portfolio_price_routing.py` (add tests)

**Step 1: Write failing tests for day change guardrails**

Add to `tests/test_portfolio_price_routing.py`:

```python
class TestDayChangeGuardrails:
    """Day change % must use provider 24h for crypto, cap at 300% for equity."""

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_crypto_uses_provider_24h_change(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Crypto day change should come from yfinance provider, not computed."""
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "TRUMP", "quantity": 15, "average_cost": 5.0,
                "snaptrade_price": 3.43, "raw_symbol": "TRUMP",
                "account_id": "acc1", "asset_type": "Cryptocurrency",
                "company_name": "TRUMP",
            })],
            [_mock_row({"cash": 0, "buying_power": 0})],
            [_mock_row({"worst_status": "connected"})],
            [_mock_row({"last_sync": "2026-03-01T18:00:00+00:00"})],
        ]
        mock_latest.return_value = {}
        mock_prev.return_value = {}
        mock_yf.return_value = {
            "TRUMP": {"price": 3.43, "previousClose": 3.50, "dayChange": -0.07, "dayChangePct": -2.0},
        }

        response = client.get("/portfolio")
        data = response.json()
        trump = next(p for p in data["positions"] if p["symbol"] == "TRUMP")
        # Should use provider's -2.0%, not compute from some random prev_close
        assert trump["dayChangePercent"] == -2.0

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_equity_absurd_pct_nulled(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Equity day change > 300% should be set to null."""
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "AAPL", "quantity": 10, "average_cost": 150,
                "snaptrade_price": 178, "raw_symbol": "AAPL",
                "account_id": "acc1", "asset_type": "Common Stock",
                "company_name": "Apple Inc.",
            })],
            [_mock_row({"cash": 0, "buying_power": 0})],
            [_mock_row({"worst_status": "connected"})],
            [_mock_row({"last_sync": "2026-03-01T18:00:00+00:00"})],
        ]
        # Databento returns a normal latest close but a stale/wrong prev close
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {"AAPL": 0.50}  # Absurd → 35500% change
        mock_yf.return_value = {}

        response = client.get("/portfolio")
        data = response.json()
        aapl = next(p for p in data["positions"] if p["symbol"] == "AAPL")
        # Should be null because >300%
        assert aapl["dayChangePercent"] is None
        assert aapl["dayChange"] is None

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_equity_zero_prev_close_nulled(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Equity with prev_close=0 should have null day change."""
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "AAPL", "quantity": 10, "average_cost": 150,
                "snaptrade_price": 178, "raw_symbol": "AAPL",
                "account_id": "acc1", "asset_type": "Common Stock",
                "company_name": "Apple Inc.",
            })],
            [_mock_row({"cash": 0, "buying_power": 0})],
            [_mock_row({"worst_status": "connected"})],
            [_mock_row({"last_sync": "2026-03-01T18:00:00+00:00"})],
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {}  # No prev close
        mock_yf.return_value = {}

        response = client.get("/portfolio")
        data = response.json()
        aapl = next(p for p in data["positions"] if p["symbol"] == "AAPL")
        assert aapl["dayChangePercent"] is None
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_portfolio_price_routing.py::TestDayChangeGuardrails -v`
Expected: FAIL — crypto still computes from prev_close, no 300% cap

**Step 3: Implement day change guardrails**

In `app/routes/portfolio.py`, replace lines 325-337 (day change calculation block) with:

```python
            # Day change calculation — separate logic for crypto vs equity
            is_crypto = symbol in _CRYPTO_SYMBOLS

            if is_crypto:
                # Crypto: ALWAYS use provider's 24h change (never compute from prev_close)
                if yf_quote and yf_quote.get("dayChangePct") is not None:
                    day_change_pct = yf_quote["dayChangePct"]
                    day_change = quantity * current_price * (day_change_pct / 100)
                else:
                    day_change_pct = None
                    day_change = None
                prev_close = yf_quote.get("previousClose") if yf_quote else None
                prev_close_source = "yfinance" if prev_close else None
            else:
                # Equity: compute from prev_close with guardrails
                prev_close = prev_closes_map.get(symbol)
                prev_close_source = "databento" if prev_close else None
                if not prev_close and yf_quote:
                    prev_close = yf_quote.get("previousClose")
                    if prev_close:
                        prev_close_source = "yfinance"

                if prev_close and prev_close > 0:
                    day_change_pct = ((current_price - prev_close) / prev_close) * 100
                    day_change = (current_price - prev_close) * quantity
                    # Guard: cap at 300% — treat as data error
                    if abs(day_change_pct) > 300:
                        logger.warning(
                            f"⚠️ {symbol}: day_change_pct={day_change_pct:.1f}% exceeds 300%% cap, "
                            f"nulling (current={current_price}, prev={prev_close})"
                        )
                        day_change_pct = None
                        day_change = None
                else:
                    day_change_pct = None
                    day_change = None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_portfolio_price_routing.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -v -m "not openai and not integration" --tb=short`

**Step 6: Commit**

```bash
git add app/routes/portfolio.py tests/test_portfolio_price_routing.py
git commit -m "fix: crypto uses provider 24h change, equity capped at 300%"
```

---

## Task 4: Fix movers endpoint with same price routing + guardrails

**Files:**
- Modify: `app/routes/portfolio.py:700-770` (movers endpoint)

**Step 1: Write failing test for movers crypto routing**

Add to `tests/test_portfolio_price_routing.py`:

```python
class TestMoversEndpoint:
    """Movers must also use crypto-safe price routing."""

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_movers_excludes_null_day_change(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Items with null dayChangePct should not appear in movers."""
        mock_sql.return_value = [
            _mock_row({"symbol": "AAPL", "quantity": 10, "average_cost": 150, "snaptrade_price": 178}),
            _mock_row({"symbol": "BAD", "quantity": 5, "average_cost": 100, "snaptrade_price": 50}),
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {"AAPL": 176.0}  # BAD has no prev close
        mock_yf.return_value = {}

        response = client.get("/portfolio/movers?limit=3")
        data = response.json()
        symbols_in_movers = (
            [g["symbol"] for g in data["topGainers"]] +
            [l["symbol"] for l in data["topLosers"]]
        )
        assert "BAD" not in symbols_in_movers, "Items without valid day change should be excluded"

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_movers_crypto_not_sent_to_databento(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Crypto symbols should be routed to yfinance in movers endpoint too."""
        mock_sql.return_value = [
            _mock_row({"symbol": "BTC", "quantity": 0.001, "average_cost": 50000, "snaptrade_price": 65000}),
            _mock_row({"symbol": "AAPL", "quantity": 10, "average_cost": 150, "snaptrade_price": 178}),
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {"AAPL": 176.0}
        mock_yf.return_value = {
            "BTC": {"price": 65842.71, "previousClose": 65000.0, "dayChange": 842.71, "dayChangePct": 1.30},
        }

        response = client.get("/portfolio/movers?limit=3")
        assert response.status_code == 200

        # Verify Databento only got equity symbols
        latest_args = mock_latest.call_args[0][0]
        assert "BTC" not in latest_args
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_portfolio_price_routing.py::TestMoversEndpoint -v`
Expected: FAIL

**Step 3: Apply same price routing fix to movers endpoint**

In `app/routes/portfolio.py`, replace the movers price fetching block (around lines 700-770) with:

```python
        # Collect symbols and batch fetch prices — same crypto-safe routing as GET /portfolio
        from src.market_data_service import _CRYPTO_SYMBOLS, get_realtime_quotes_batch

        position_rows = []
        symbols = []
        for row in positions_data:
            rd: dict = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            position_rows.append(rd)
            symbols.append(rd["symbol"])

        crypto_syms = [s for s in symbols if s in _CRYPTO_SYMBOLS]
        equity_syms = [s for s in symbols if s not in _CRYPTO_SYMBOLS]

        prices_map = get_latest_closes_batch(equity_syms) if equity_syms else {}
        prev_closes_map = get_previous_closes_batch(equity_syms) if equity_syms else {}

        yf_quotes: dict = {}
        yf_needed = crypto_syms + [s for s in equity_syms if s not in prices_map]
        if yf_needed:
            try:
                yf_quotes = get_realtime_quotes_batch(yf_needed)
            except Exception as exc:
                logger.debug("yfinance batch quotes skipped: %s", exc)

        # Build mover items with crypto-aware day change
        items: list[dict] = []

        for rd in position_rows:
            symbol = rd["symbol"]
            qty = float(rd["quantity"] or 0)
            avg_cost = float(rd["average_cost"] or 0)
            is_crypto = symbol in _CRYPTO_SYMBOLS

            # Price cascade (same as GET /portfolio)
            snaptrade_price = float(rd.get("snaptrade_price") or 0)
            databento_price = prices_map.get(symbol)
            yf_quote = yf_quotes.get(symbol)

            if not is_crypto and databento_price:
                current_price = databento_price
            elif snaptrade_price > 0:
                current_price = snaptrade_price
            elif yf_quote:
                current_price = yf_quote["price"]
            else:
                current_price = avg_cost

            equity = qty * current_price

            # Day change — crypto vs equity
            day_change = None
            day_change_pct = None

            if is_crypto:
                if yf_quote and yf_quote.get("dayChangePct") is not None:
                    day_change_pct = yf_quote["dayChangePct"]
                    day_change = qty * current_price * (day_change_pct / 100)
            else:
                prev_close = prev_closes_map.get(symbol)
                if not prev_close and yf_quote:
                    prev_close = yf_quote.get("previousClose")
                if prev_close and prev_close > 0:
                    day_change_pct = ((current_price - prev_close) / prev_close) * 100
                    day_change = (current_price - prev_close) * qty
                    if abs(day_change_pct) > 300:
                        day_change_pct = None
                        day_change = None

            open_pnl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0

            items.append({
                "symbol": symbol,
                "currentPrice": r2(current_price),
                "previousClose": r2n(prev_closes_map.get(symbol) or (yf_quote.get("previousClose") if yf_quote else None)),
                "dayChange": r2n(day_change),
                "dayChangePct": r2n(day_change_pct),
                "quantity": qty,
                "equity": r2(equity),
                "openPnlPct": r2(open_pnl_pct),
            })
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_portfolio_price_routing.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add app/routes/portfolio.py tests/test_portfolio_price_routing.py
git commit -m "fix: apply crypto-safe price routing and day change guards to movers endpoint"
```

---

## Task 5: Add tvSymbol to Position model

**Files:**
- Modify: `app/routes/portfolio.py:49-66` (Position model)
- Modify: `app/routes/portfolio.py:339-365` (Position construction)
- Modify: `tests/test_portfolio_price_routing.py`

**Step 1: Write failing test**

Add to `tests/test_portfolio_price_routing.py`:

```python
class TestTvSymbol:
    """Position response must include tvSymbol for TradingView."""

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_crypto_has_canonical_tv_symbol(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "BTC", "quantity": 0.001, "average_cost": 50000,
                "snaptrade_price": 65000, "raw_symbol": "BTC",
                "account_id": "acc1", "asset_type": "Cryptocurrency",
                "company_name": "Bitcoin",
            })],
            [_mock_row({"cash": 0, "buying_power": 0})],
            [_mock_row({"worst_status": "connected"})],
            [_mock_row({"last_sync": "2026-03-01T18:00:00+00:00"})],
        ]
        mock_latest.return_value = {}
        mock_prev.return_value = {}
        mock_yf.return_value = {
            "BTC": {"price": 65842.71, "previousClose": 65000.0, "dayChange": 842.71, "dayChangePct": 1.30},
        }

        response = client.get("/portfolio")
        data = response.json()
        btc = next(p for p in data["positions"] if p["symbol"] == "BTC")
        assert btc["tvSymbol"] == "COINBASE:BTCUSD"

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_equity_has_tv_symbol(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "AAPL", "quantity": 10, "average_cost": 150,
                "snaptrade_price": 178, "raw_symbol": "AAPL",
                "account_id": "acc1", "asset_type": "Common Stock",
                "company_name": "Apple Inc.", "exchange_code": "NASDAQ",
            })],
            [_mock_row({"cash": 0, "buying_power": 0})],
            [_mock_row({"worst_status": "connected"})],
            [_mock_row({"last_sync": "2026-03-01T18:00:00+00:00"})],
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {"AAPL": 176.0}
        mock_yf.return_value = {}

        response = client.get("/portfolio")
        data = response.json()
        aapl = next(p for p in data["positions"] if p["symbol"] == "AAPL")
        # Should have exchange-qualified TV symbol
        assert "tvSymbol" in aapl
```

**Step 2: Run test, confirm fail**

Run: `pytest tests/test_portfolio_price_routing.py::TestTvSymbol -v`

**Step 3: Implement tvSymbol**

Add to `Position` model (line 66):
```python
    tvSymbol: str | None = None  # TradingView widget symbol (e.g. "COINBASE:BTCUSD", "NASDAQ:AAPL")
```

Add `exchange_code` to the positions SQL query (in the SELECT clause around line 170):
```sql
        p.exchange_code,
```

Add a helper function before the `get_portfolio` function:
```python
def _resolve_tv_symbol(symbol: str, exchange_code: str | None = None) -> str:
    """Resolve a TradingView-compatible symbol string."""
    from src.market_data_service import CRYPTO_IDENTITY
    # Crypto: use canonical tv_symbol
    identity = CRYPTO_IDENTITY.get(symbol)
    if identity:
        return identity["tv_symbol"]
    # Equity: use exchange_code if available
    if exchange_code:
        ex = exchange_code.upper()
        if ex in ("XNAS", "NASDAQ"):
            return f"NASDAQ:{symbol}"
        if ex in ("XNYS", "NYSE"):
            return f"NYSE:{symbol}"
        if ex in ("ARCX", "ARCA", "NYSEARCA"):
            return f"AMEX:{symbol}"
    return symbol
```

In the Position construction block (around line 339-365), add:
```python
                    tvSymbol=_resolve_tv_symbol(symbol, row_dict.get("exchange_code")),
```

Also update the merged Position construction (around line 396-411) to propagate tvSymbol from the first group member:
```python
                        tvSymbol=first.tvSymbol,
```

**Step 4: Run tests**

Run: `pytest tests/test_portfolio_price_routing.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/routes/portfolio.py tests/test_portfolio_price_routing.py
git commit -m "feat: add tvSymbol to Position response for TradingView widgets"
```

---

## Task 6: Debug symbol trace endpoint

**Files:**
- Create: `app/routes/debug.py`
- Modify: `app/main.py:32-45` (router registration)
- Test: `tests/test_debug_route.py` (new file)

**Step 1: Write failing test**

Create `tests/test_debug_route.py`:

```python
"""Tests for GET /debug/symbol-trace endpoint."""

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


def _mock_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


@pytest.fixture
def client_with_debug():
    """Test client with debug endpoints enabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true", "DEBUG_ENDPOINTS": "1"}):
        # Force reimport to pick up env var
        import importlib
        import app.main
        importlib.reload(app.main)
        with TestClient(app.main.app) as c:
            yield c


@pytest.fixture
def client_without_debug():
    """Test client with debug endpoints disabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true", "DEBUG_ENDPOINTS": ""}, clear=False):
        import importlib
        import app.main
        importlib.reload(app.main)
        with TestClient(app.main.app) as c:
            yield c


class TestSymbolTrace:
    @patch("app.routes.debug.execute_sql")
    @patch("app.routes.debug.get_latest_closes_batch")
    @patch("app.routes.debug.get_realtime_quotes_batch")
    def test_returns_trace_for_crypto(self, mock_yf, mock_databento, mock_sql, client_with_debug):
        mock_sql.side_effect = [
            [_mock_row({"symbol": "XRP", "asset_type": "Cryptocurrency", "price": 1.35,
                        "quantity": 50, "equity": 67.5, "account_id": "acc1",
                        "sync_timestamp": "2026-03-01T18:00:00"})],
            [_mock_row({"ticker": "XRP", "asset_type": "Cryptocurrency",
                        "type_code": "crypto", "exchange_code": None})],
            [],  # activities
            [],  # orders
        ]
        mock_databento.return_value = {}
        mock_yf.return_value = {"XRP": {"price": 1.353, "previousClose": 1.30, "dayChange": 0.053, "dayChangePct": 4.08}}

        response = client_with_debug.get("/debug/symbol-trace?symbol=XRP")
        assert response.status_code == 200
        data = response.json()
        assert data["is_crypto"] is True
        assert data["tv_symbol"] == "COINBASE:XRPUSD"
        assert data["price_resolution"]["selected_source"] == "yfinance"

    def test_debug_disabled_returns_404(self, client_without_debug):
        response = client_without_debug.get("/debug/symbol-trace?symbol=XRP")
        assert response.status_code == 404
```

**Step 2: Run test, confirm fail**

Run: `pytest tests/test_debug_route.py -v`

**Step 3: Implement debug endpoint**

Create `app/routes/debug.py`:

```python
"""
Debug API routes — symbol trace and data lineage audit.

These endpoints are DISABLED by default and require DEBUG_ENDPOINTS=1 env var.
When enabled, they require the same API key auth as other endpoints.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.db import execute_sql
from src.market_data_service import (
    CRYPTO_IDENTITY,
    _CRYPTO_SYMBOLS,
    get_realtime_quotes_batch,
)
from src.price_service import get_latest_closes_batch

logger = logging.getLogger(__name__)
router = APIRouter()


class PriceResolution(BaseModel):
    databento_hit: bool
    databento_price: Optional[float] = None
    yfinance_symbol: Optional[str] = None
    yfinance_price: Optional[float] = None
    snaptrade_price: Optional[float] = None
    selected_source: str
    selected_price: float


class SymbolTraceResponse(BaseModel):
    symbol: str
    is_crypto: bool
    canonical_quote_symbol: Optional[str] = None
    tv_symbol: Optional[str] = None
    positions: list[dict[str, Any]]
    symbols_row: Optional[dict[str, Any]] = None
    recent_activities: list[dict[str, Any]]
    recent_orders: list[dict[str, Any]]
    price_resolution: PriceResolution


@router.get("/symbol-trace", response_model=SymbolTraceResponse)
async def symbol_trace(
    symbol: str = Query(..., description="Ticker symbol to trace"),
    account_id: Optional[str] = Query(None, description="Filter to specific account"),
):
    """Trace a symbol through the entire data pipeline for debugging."""
    symbol = symbol.upper().strip()
    is_crypto = symbol in _CRYPTO_SYMBOLS
    identity = CRYPTO_IDENTITY.get(symbol)

    # 1. Positions rows
    pos_query = "SELECT * FROM positions WHERE UPPER(symbol) = UPPER(:symbol)"
    pos_params: dict = {"symbol": symbol}
    if account_id:
        pos_query += " AND account_id = :account_id"
        pos_params["account_id"] = account_id
    positions_data = execute_sql(pos_query, params=pos_params, fetch_results=True)
    positions = [dict(r._mapping) for r in (positions_data or [])]
    # Convert non-serializable types
    for p in positions:
        for k, v in p.items():
            if hasattr(v, "isoformat"):
                p[k] = v.isoformat()
            elif v is not None and not isinstance(v, (str, int, float, bool)):
                p[k] = str(v)

    # 2. Symbols table row
    sym_data = execute_sql(
        "SELECT * FROM symbols WHERE UPPER(ticker) = UPPER(:symbol) LIMIT 1",
        params={"symbol": symbol}, fetch_results=True,
    )
    symbols_row = None
    if sym_data:
        symbols_row = dict(sym_data[0]._mapping)
        for k, v in symbols_row.items():
            if hasattr(v, "isoformat"):
                symbols_row[k] = v.isoformat()
            elif v is not None and not isinstance(v, (str, int, float, bool)):
                symbols_row[k] = str(v)

    # 3. Recent activities
    act_data = execute_sql(
        "SELECT id, activity_type, trade_date, amount, price, units, symbol "
        "FROM activities WHERE UPPER(symbol) = UPPER(:symbol) "
        "ORDER BY trade_date DESC LIMIT 5",
        params={"symbol": symbol}, fetch_results=True,
    )
    activities = []
    for r in (act_data or []):
        d = dict(r._mapping)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif v is not None and not isinstance(v, (str, int, float, bool)):
                d[k] = str(v)
        activities.append(d)

    # 4. Recent orders
    ord_data = execute_sql(
        "SELECT brokerage_order_id, symbol, action, status, execution_price "
        "FROM orders WHERE UPPER(symbol) = UPPER(:symbol) "
        "ORDER BY time_placed DESC LIMIT 5",
        params={"symbol": symbol}, fetch_results=True,
    )
    orders = []
    for r in (ord_data or []):
        d = dict(r._mapping)
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif v is not None and not isinstance(v, (str, int, float, bool)):
                d[k] = str(v)
        orders.append(d)

    # 5. Price resolution trace
    snaptrade_price = float(positions[0].get("price", 0)) if positions else 0.0

    # Check Databento (only for equity — crypto should get nothing)
    if is_crypto:
        databento_price = None
    else:
        databento_map = get_latest_closes_batch([symbol])
        databento_price = databento_map.get(symbol)

    # Check yfinance
    yf_symbol = identity["quote_symbol"] if identity else symbol
    yf_map = get_realtime_quotes_batch([symbol])
    yf_price = yf_map[symbol]["price"] if symbol in yf_map else None

    # Determine selected source (same cascade as GET /portfolio)
    if not is_crypto and databento_price:
        selected_source = "databento"
        selected_price = float(databento_price)
    elif snaptrade_price > 0:
        selected_source = "snaptrade"
        selected_price = snaptrade_price
    elif yf_price:
        selected_source = "yfinance"
        selected_price = float(yf_price)
    else:
        selected_source = "none"
        selected_price = 0.0

    return SymbolTraceResponse(
        symbol=symbol,
        is_crypto=is_crypto,
        canonical_quote_symbol=identity["quote_symbol"] if identity else None,
        tv_symbol=identity["tv_symbol"] if identity else None,
        positions=positions,
        symbols_row=symbols_row,
        recent_activities=activities,
        recent_orders=orders,
        price_resolution=PriceResolution(
            databento_hit=databento_price is not None,
            databento_price=float(databento_price) if databento_price else None,
            yfinance_symbol=yf_symbol if is_crypto else None,
            yfinance_price=float(yf_price) if yf_price else None,
            snaptrade_price=snaptrade_price if snaptrade_price > 0 else None,
            selected_source=selected_source,
            selected_price=selected_price,
        ),
    )
```

Register in `app/main.py` — add after the existing imports (around line 45):

```python
import os
# Conditionally import debug routes
if os.getenv("DEBUG_ENDPOINTS") == "1":
    from app.routes import debug as debug_routes
```

And add the router registration (after the other `app.include_router` calls):

```python
# Debug routes — disabled by default, require DEBUG_ENDPOINTS=1
if os.getenv("DEBUG_ENDPOINTS") == "1":
    app.include_router(
        debug_routes.router,
        prefix="/debug",
        tags=["Debug"],
        dependencies=[Depends(require_api_key)],
    )
    logger.warning("⚠️ Debug endpoints are ENABLED — disable in production")
```

**Step 4: Run tests**

Run: `pytest tests/test_debug_route.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/routes/debug.py app/main.py tests/test_debug_route.py
git commit -m "feat: add debug symbol-trace endpoint for data lineage auditing"
```

---

## Task 7: Orders default filter (BUY/SELL only) + UUID symbol guard

**Files:**
- Modify: `app/routes/orders.py:69-130`
- Modify: `tests/test_orders_formatting.py`

**Step 1: Write failing test**

Add to `tests/test_orders_formatting.py` (or create if structure differs):

```python
class TestOrdersDefaultFilter:
    @patch("app.routes.orders.execute_sql")
    def test_default_excludes_drip_dividend(self, mock_sql, client):
        """Default orders should only include BUY/SELL/BUY_OPEN/SELL_CLOSE."""
        mock_sql.return_value = []
        client.get("/orders?limit=5")

        # Check that the SQL query filters by action
        query = mock_sql.call_args[0][0]
        assert "action" in query.lower() or "IN" in query, \
            "Default orders query must filter by BUY/SELL actions"


class TestOrdersSymbolGuard:
    @patch("app.routes.orders.execute_sql")
    def test_uuid_symbol_replaced(self, mock_sql, client):
        """Orders with UUID-like symbols should be cleaned."""
        mock_sql.return_value = [_mock_row({
            "id": "order-1",
            "symbol": "a3b4c5d6-e7f8-9012-3456-789012345678",
            "side": "BUY", "type": "market", "quantity": 10,
            "filled_quantity": 10, "limit_price": None, "stop_price": None,
            "execution_price": 100, "status": "EXECUTED",
            "time_placed": "2026-03-01T12:00:00", "time_executed": "2026-03-01T12:00:01",
            "notified": False,
        })]

        response = client.get("/orders?limit=5")
        data = response.json()
        if data["orders"]:
            assert not data["orders"][0]["symbol"].startswith("a3b4c5d6"), \
                "UUID-like symbols should be resolved or marked as Unknown"
```

**Step 2: Run test, confirm fail**

**Step 3: Implement default action filter + UUID guard**

In `app/routes/orders.py`, modify the `get_orders` function:

Add a new parameter:
```python
    include_drip: bool = Query(False, description="Include DIVIDEND/REI reinvestment orders"),
```

Before `where_clause`, add default action filter:
```python
        # Default: only trade-relevant actions (exclude DRIP/dividends)
        if not include_drip:
            _trade_actions = ("BUY", "SELL", "BUY_OPEN", "SELL_CLOSE", "BUY_TO_COVER", "SELL_SHORT")
            conditions.append(f"o.action IN ({','.join(':act_' + str(i) for i in range(len(_trade_actions)))})")
            for i, act in enumerate(_trade_actions):
                params[f"act_{i}"] = act
```

In the order construction loop, add UUID symbol guard:
```python
            import re
            symbol = rd.get("symbol", "")
            # Guard: UUID-like symbols → resolve or mark Unknown
            if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-', symbol, re.IGNORECASE):
                symbol = "Unknown"
```

**Step 4: Run tests**

Run: `pytest tests/test_orders_formatting.py -v`

**Step 5: Commit**

```bash
git add app/routes/orders.py tests/test_orders_formatting.py
git commit -m "fix: default orders filter to BUY/SELL only, guard UUID symbols"
```

---

## Task 8: Ideas context endpoint

**Files:**
- Modify: `app/routes/ideas.py` (add new endpoint)
- Test: `tests/test_ideas_route.py` (add test)

**Step 1: Write failing test**

Add to `tests/test_ideas_route.py`:

```python
class TestIdeaContext:
    @patch("app.routes.ideas.execute_sql")
    def test_returns_context_with_surrounding_messages(self, mock_sql, client):
        """GET /ideas/{id}/context returns parent message + surrounding context."""
        idea_row = {**SAMPLE_IDEA_ROW, "origin_message_id": "msg-123"}
        mock_sql.side_effect = [
            [_mock_row(idea_row)],  # idea query
            [_mock_row({  # parent message
                "message_id": "msg-123", "content": "Buy AAPL on the dip",
                "author": "qaisy", "timestamp": "2026-02-28T14:30:00",
                "channel": "trading-ideas",
            })],
            [  # context messages (±5)
                _mock_row({"message_id": "msg-121", "content": "Market opening strong",
                           "author": "user2", "timestamp": "2026-02-28T14:28:00", "channel": "trading-ideas"}),
                _mock_row({"message_id": "msg-122", "content": "Watching tech names",
                           "author": "qaisy", "timestamp": "2026-02-28T14:29:00", "channel": "trading-ideas"}),
                _mock_row({"message_id": "msg-123", "content": "Buy AAPL on the dip",
                           "author": "qaisy", "timestamp": "2026-02-28T14:30:00", "channel": "trading-ideas"}),
                _mock_row({"message_id": "msg-124", "content": "Good call",
                           "author": "user3", "timestamp": "2026-02-28T14:31:00", "channel": "trading-ideas"}),
            ],
        ]

        response = client.get(f"/ideas/{SAMPLE_UUID}/context")
        assert response.status_code == 200
        data = response.json()
        assert data["parentMessage"]["messageId"] == "msg-123"
        assert len(data["contextMessages"]) >= 3
        # Parent message should be marked
        parent_in_context = [m for m in data["contextMessages"] if m["isParent"]]
        assert len(parent_in_context) == 1
```

**Step 2: Run test, confirm fail**

**Step 3: Implement context endpoint**

Add to `app/routes/ideas.py`:

```python
class ContextMessage(BaseModel):
    messageId: str
    content: str
    author: str
    sentAt: str
    channel: str
    isParent: bool = False


class IdeaContextResponse(BaseModel):
    idea: IdeaOut
    parentMessage: Optional[ContextMessage] = None
    contextMessages: list[ContextMessage] = []


@router.get("/{idea_id}/context", response_model=IdeaContextResponse)
async def get_idea_context(
    idea_id: str = Path(..., description="Idea UUID"),
    context_window: int = Query(5, ge=1, le=20, description="Messages before/after parent"),
):
    """Get idea with parent Discord message and surrounding context."""
    # 1. Fetch the idea
    idea_rows = execute_sql(
        "SELECT * FROM user_ideas WHERE id = :id",
        params={"id": idea_id}, fetch_results=True,
    )
    if not idea_rows:
        raise HTTPException(status_code=404, detail="Idea not found")

    row = dict(idea_rows[0]._mapping)
    idea = IdeaOut(
        id=str(row["id"]),
        symbol=row.get("symbol"),
        symbols=row.get("symbols") or [],
        content=row["content"],
        source=row["source"],
        status=row["status"],
        tags=row.get("tags") or [],
        originMessageId=row.get("origin_message_id"),
        contentHash=row["content_hash"],
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )

    # 2. Fetch parent message
    parent_msg = None
    context_msgs: list[ContextMessage] = []

    if idea.originMessageId:
        msg_rows = execute_sql(
            "SELECT message_id, content, author, timestamp, channel "
            "FROM discord_messages WHERE message_id = :msg_id",
            params={"msg_id": idea.originMessageId}, fetch_results=True,
        )
        if msg_rows:
            mr = dict(msg_rows[0]._mapping)
            parent_msg = ContextMessage(
                messageId=mr["message_id"],
                content=mr["content"],
                author=mr["author"],
                sentAt=str(mr["timestamp"]),
                channel=mr["channel"],
                isParent=True,
            )

            # 3. Fetch surrounding messages from same channel
            ctx_rows = execute_sql(
                """
                (SELECT message_id, content, author, timestamp, channel
                 FROM discord_messages
                 WHERE channel = :channel AND timestamp <= :ts
                 ORDER BY timestamp DESC
                 LIMIT :before)
                UNION ALL
                (SELECT message_id, content, author, timestamp, channel
                 FROM discord_messages
                 WHERE channel = :channel AND timestamp > :ts
                 ORDER BY timestamp ASC
                 LIMIT :after)
                ORDER BY timestamp ASC
                """,
                params={
                    "channel": mr["channel"],
                    "ts": mr["timestamp"],
                    "before": context_window + 1,  # +1 to include parent
                    "after": context_window,
                },
                fetch_results=True,
            )
            for cr in (ctx_rows or []):
                cd = dict(cr._mapping)
                context_msgs.append(ContextMessage(
                    messageId=cd["message_id"],
                    content=cd["content"],
                    author=cd["author"],
                    sentAt=str(cd["timestamp"]),
                    channel=cd["channel"],
                    isParent=cd["message_id"] == idea.originMessageId,
                ))

    return IdeaContextResponse(
        idea=idea,
        parentMessage=parent_msg,
        contextMessages=context_msgs,
    )
```

**Step 4: Run tests**

Run: `pytest tests/test_ideas_route.py::TestIdeaContext -v`
Expected: PASS

**Step 5: Commit**

```bash
git add app/routes/ideas.py tests/test_ideas_route.py
git commit -m "feat: add ideas context endpoint with surrounding Discord messages"
```

---

## Task 9: Frontend — Use tvSymbol + update types

**Files:**
- Modify: `frontend/src/types/api.ts:31-47` (add tvSymbol to Position)
- Modify: `frontend/src/components/stock/TradingViewChart.tsx:120-168`
- Modify: `frontend/src/app/api/orders/route.ts`

**Step 1: Update Position type**

In `frontend/src/types/api.ts`, add to Position interface:
```typescript
  tvSymbol?: string; // TradingView widget symbol (e.g. "COINBASE:BTCUSD", "NASDAQ:AAPL")
```

**Step 2: Update TradingViewChart to use tvSymbol**

In `frontend/src/components/stock/TradingViewChart.tsx`, replace the `formatSymbol` function (lines 120-168) with:

```typescript
// Format symbol for TradingView — prefer backend-provided tvSymbol
function formatSymbol(symbol: string, tvSymbol?: string): string {
  // If backend provides a canonical TV symbol, use it directly
  if (tvSymbol) return tvSymbol;

  // Fallback: compute from raw ticker (legacy path)
  const cleanSymbol = symbol.toUpperCase().trim();

  // Crypto — use CRYPTO: prefix with USD suffix
  const cryptoSymbols = ['BTC', 'ETH', 'XRP', 'SOL', 'ADA', 'DOT', 'DOGE', 'LINK', 'AVAX', 'MATIC', 'SHIB', 'PEPE', 'TRUMP'];
  if (cryptoSymbols.includes(cleanSymbol)) {
    return `CRYPTO:${cleanSymbol}USD`;
  }

  // Default to auto-detection (TradingView will figure it out)
  return cleanSymbol;
}
```

Update all call sites of `formatSymbol` to pass `tvSymbol` when available from position data. The stock page at `/stock/[ticker]` won't have tvSymbol from URL params, so the fallback path handles it.

**Step 3: Update BFF orders route to pass include_drip param**

In `frontend/src/app/api/orders/route.ts`, add support for the new param:
```typescript
    const includeDrip = searchParams.get('include_drip') || '';
    if (includeDrip) params.set('include_drip', includeDrip);
```

**Step 4: Verify frontend builds**

Run: `cd frontend && npm run build`

**Step 5: Commit**

```bash
cd frontend
git add src/types/api.ts src/components/stock/TradingViewChart.tsx src/app/api/orders/route.ts
git commit -m "feat: use backend tvSymbol for TradingView, update orders BFF route"
```

---

## Task 10: Frontend — Ideas context modal

**Files:**
- Modify: `frontend/src/components/ideas/IdeaDetailDrawer.tsx`
- Create: `frontend/src/app/api/ideas/[id]/context/route.ts`
- Modify: `frontend/src/types/ideas.ts` (add context types)

**Step 1: Add BFF route for ideas context**

Create `frontend/src/app/api/ideas/[id]/context/route.ts`:

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { backendFetch, authGuard } from '@/lib/api-client';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    await authGuard();
    const { id } = await params;

    const response = await backendFetch(`/ideas/${id}/context`, {
      next: { revalidate: 60 },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to fetch idea context' },
        { status: response.status }
      );
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    if (error instanceof Response) return error;
    return NextResponse.json({ error: 'Failed to connect to backend' }, { status: 502 });
  }
}
```

**Step 2: Add types for context response**

In `frontend/src/types/ideas.ts`, add:

```typescript
export interface ContextMessage {
  messageId: string;
  content: string;
  author: string;
  sentAt: string;
  channel: string;
  isParent: boolean;
}

export interface IdeaContextResponse {
  idea: UserIdea;
  parentMessage: ContextMessage | null;
  contextMessages: ContextMessage[];
}
```

**Step 3: Add context section to IdeaDetailDrawer**

In `IdeaDetailDrawer.tsx`, add state and fetch logic for context:

```typescript
  const [contextData, setContextData] = useState<IdeaContextResponse | null>(null);
  const [loadingContext, setLoadingContext] = useState(false);

  const loadContext = useCallback(async () => {
    if (!idea?.originMessageId) return;
    setLoadingContext(true);
    try {
      const res = await fetch(`/api/ideas/${idea.id}/context`);
      if (res.ok) setContextData(await res.json());
    } catch { /* silent */ }
    setLoadingContext(false);
  }, [idea]);
```

Add a "View Context" button in the drawer that calls `loadContext()` and renders the context messages when loaded. Highlight the parent message with a different background. Add a "View in Raw" link that navigates to `/messages?highlight=${idea.originMessageId}`.

**Step 4: Verify frontend builds**

Run: `cd frontend && npm run build`

**Step 5: Commit**

```bash
cd frontend
git add src/app/api/ideas/[id]/context/route.ts src/types/ideas.ts src/components/ideas/IdeaDetailDrawer.tsx
git commit -m "feat: add ideas context modal with surrounding Discord messages"
```

---

## Task 11: End-to-end validation

**Step 1: Enable debug endpoint and run symbol traces**

```bash
DEBUG_ENDPOINTS=1 python -c "
import requests
BASE = 'http://localhost:8000'
HEADERS = {'Authorization': 'Bearer YOUR_API_KEY'}
for sym in ['XRP', 'BTC', 'TRUMP', 'NVDA', 'GOOGL']:
    r = requests.get(f'{BASE}/debug/symbol-trace?symbol={sym}', headers=HEADERS)
    data = r.json()
    print(f'{sym}: is_crypto={data[\"is_crypto\"]}, '
          f'source={data[\"price_resolution\"][\"selected_source\"]}, '
          f'price=${data[\"price_resolution\"][\"selected_price\"]:.2f}, '
          f'tv={data[\"tv_symbol\"]}')
"
```

Expected output (approximately):
```
XRP: is_crypto=True, source=yfinance, price=$1.35, tv=COINBASE:XRPUSD
BTC: is_crypto=True, source=yfinance, price=$65842.71, tv=COINBASE:BTCUSD
TRUMP: is_crypto=True, source=yfinance, price=$3.43, tv=CRYPTO:TRUMPUSD
NVDA: is_crypto=False, source=databento, price=$177.80, tv=NASDAQ:NVDA
GOOGL: is_crypto=False, source=databento, price=$309.20, tv=NASDAQ:GOOGL
```

**Step 2: Validate portfolio endpoints**

```bash
# Crypto positions
curl -s -H "Authorization: Bearer KEY" localhost:8000/portfolio?asset_class=crypto | python -m json.tool | grep -E '"symbol"|"currentPrice"|"dayChange"'

# Equity positions
curl -s -H "Authorization: Bearer KEY" localhost:8000/portfolio?asset_class=equity | python -m json.tool | grep -E '"symbol"|"currentPrice"|"dayChange"'

# Movers
curl -s -H "Authorization: Bearer KEY" localhost:8000/portfolio/movers?limit=5 | python -m json.tool
```

Acceptance criteria:
- XRP appears only once, as crypto, price ~$1.35
- BTC price ~$65,842
- TRUMP price ~$3.43, no insane day change %
- No duplicate NVDA/GOOGL/AMZN rows
- Top Movers percentages are all believable (no > 300%)
- Movers excludes null day_change items from ranking

**Step 3: Run full backend test suite**

```bash
pytest tests/ -v -m "not openai and not integration" --tb=short
```

**Step 4: Run frontend build**

```bash
cd frontend && npm run build
```

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: end-to-end validation of data quality overhaul"
```

---

## Summary of All Commits

| # | Message | Workstream |
|---|---------|------------|
| 1 | `feat: add CRYPTO_IDENTITY dict for canonical crypto symbol resolution` | WS2 |
| 2 | `fix: route crypto symbols to yfinance, never to Databento ohlcv_daily` | WS2 |
| 3 | `fix: crypto uses provider 24h change, equity capped at 300%` | WS3 |
| 4 | `fix: apply crypto-safe price routing and day change guards to movers endpoint` | WS3 |
| 5 | `feat: add tvSymbol to Position response for TradingView widgets` | WS7 |
| 6 | `feat: add debug symbol-trace endpoint for data lineage auditing` | WS1 |
| 7 | `fix: default orders filter to BUY/SELL only, guard UUID symbols` | WS5 |
| 8 | `feat: add ideas context endpoint with surrounding Discord messages` | WS6 |
| 9 | `feat: use backend tvSymbol for TradingView, update orders BFF route` | WS7 |
| 10 | `feat: add ideas context modal with surrounding Discord messages` | WS6 |
| 11 | `chore: end-to-end validation of data quality overhaul` | All |
