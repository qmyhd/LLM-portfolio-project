# Data Quality Overhaul — Design Document

**Date**: 2026-03-01
**Branch**: `hoodui`
**Scope**: Backend + Frontend data quality fixes across 7 workstreams

## Problem Statement

Multiple data quality issues in the portfolio display pipeline:

1. **Crypto prices wildly wrong** — BTC shows ~$29 instead of ~$65,842. Root cause: Databento `ohlcv_daily` has equity tickers that collide with crypto symbols (BTC = Grayscale Bitcoin Trust, ETH = Ethan Allen, SOL = Renesola, XRP = equity). Price cascade checks Databento first for ALL symbols, so crypto gets equity prices.

2. **XRP identity collision** — XRP appears as both equity and crypto because the ticker exists in both domains. No canonical identity separates them.

3. **Day change % explosions** — TRUMP shows insane % because prev_price comes from the wrong instrument (equity TRUMP in Databento) while current_price comes from yfinance crypto (TRUMP-USD). Different base prices → absurd %.

4. **Duplicate holdings rows** — Same symbol appearing multiple times in the UI (GOOGL, NVDA, AMZN, AMD).

5. **Recent Orders garbage symbols** — Some order rows display UUID-like strings instead of ticker symbols.

6. **Ideas lack context navigation** — No way to click an idea and see the surrounding Discord conversation.

7. **TradingView crypto charts** — Symbols generated from raw tickers, not canonical exchange-qualified identifiers.

## Ground Truth Reference (as of 6:15 PM ET, 2026-03-01)

| Symbol | Expected Price | Source |
|--------|---------------|--------|
| XRP | $1.353 | Crypto |
| BTC | $65,842.71 | Crypto |
| TRUMP | $3.43 | Crypto |
| NVDA | $177.80 | Equity |
| GOOGL | $309.20 | Equity |

Robinhood totals: Individual Stocks & ETFs = $18,329.88 (148 items), Crypto = $1,207.99 (9 items).

---

## Workstream 1: Debug Symbol Trace Endpoint

### Design

New endpoint `GET /debug/symbol-trace?symbol=XRP&account_id=...`

**Response shape:**
```json
{
  "symbol": "XRP",
  "positions": [{ "symbol", "asset_type", "price", "quantity", "equity", "account_id", "sync_timestamp" }],
  "symbols_row": { "ticker", "asset_type", "type_code", "exchange_code" },
  "recent_activities": [{ "id", "activity_type", "trade_date", "amount", "price", "units" }],
  "recent_orders": [{ "brokerage_order_id", "symbol", "action", "status", "execution_price" }],
  "price_resolution": {
    "databento_hit": true/false,
    "databento_price": 15.16,
    "yfinance_symbol": "XRP-USD",
    "yfinance_price": 1.353,
    "snaptrade_price": 1.35,
    "selected_source": "yfinance",
    "selected_price": 1.353
  },
  "tv_symbol": "COINBASE:XRPUSD",
  "is_crypto": true,
  "canonical_quote_symbol": "XRP-USD"
}
```

**Access control:**
- Disabled by default (requires `DEBUG_ENDPOINTS=1` env var)
- When enabled, requires admin auth (API key or bearer token check)
- Never enabled in production unless explicitly set

**File**: `app/routes/debug.py` — new file, registered conditionally in `app/main.py`.

---

## Workstream 2: Crypto Price Identity Fix (Option A + partial C)

### Root Cause

`portfolio.py:247-253` calls `get_latest_closes_batch(ALL_SYMBOLS)` and `get_previous_closes_batch(ALL_SYMBOLS)`. Databento `ohlcv_daily` has equity entries for BTC, ETH, SOL, XRP etc. These equity prices are returned and used for crypto positions. The yfinance fallback (which correctly adds `-USD` suffix) never fires.

### Fix: Split by asset type BEFORE price lookup

In `portfolio.py`, after asset_type determination but before price fetching:

```python
crypto_syms = [s for s in symbols_to_fetch if s in _CRYPTO_SYMBOLS]
equity_syms = [s for s in symbols_to_fetch if s not in _CRYPTO_SYMBOLS]

# Databento ONLY for equities
prices_map = get_latest_closes_batch(equity_syms) if equity_syms else {}
prev_closes_map = get_previous_closes_batch(equity_syms) if equity_syms else {}

# yfinance for ALL crypto + Databento misses
yf_needed = crypto_syms + [s for s in equity_syms if s not in prices_map]
if yf_needed:
    yf_quotes = get_realtime_quotes_batch(yf_needed)
```

### Canonical Crypto Symbol Storage (partial Option C)

Add a lookup table `CRYPTO_IDENTITY` in `market_data_service.py`:

```python
CRYPTO_IDENTITY: dict[str, dict] = {
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
    "PEPE":  {"quote_symbol": "PEPE-USD",  "tv_symbol": "COINBASE:PEPEUSD"},
    "TRUMP": {"quote_symbol": "TRUMP-USD", "tv_symbol": "CRYPTO:TRUMPUSD"},
}
```

This table:
- Ensures `_yf_symbol()` uses canonical quote symbols
- Provides TradingView-ready symbols passed through the API response
- Is the single source of truth for crypto identity
- Can be extended as new crypto assets are added

### API Response Enhancement

Add `tvSymbol` field to `Position` model:
- Crypto: from `CRYPTO_IDENTITY[symbol]["tv_symbol"]`
- Equity: computed from exchange_code (existing frontend logic moved to backend)
- Frontend reads `tvSymbol` directly instead of computing it

---

## Workstream 3: Day Change Guardrails

### Rules

**Crypto positions:**
- Always use yfinance provider's `dayChangePct` as-is (represents 24h change for crypto)
- Never compute from Databento prev_close (Databento doesn't cover crypto anyway after Workstream 2 fix)
- If yfinance `dayChangePct` is unavailable → `null`

**Equity positions:**
- Compute from `(current_price - prev_close) / prev_close * 100`
- If `prev_close <= 0` or missing → `day_change_pct = null`
- If `abs(day_change_pct) > 300%` → `day_change_pct = null`
- `null` values excluded from Top Movers ranking

### Implementation

In `portfolio.py` position metrics calculation block:

```python
is_crypto = sym in _CRYPTO_SYMBOLS

if is_crypto:
    # Crypto: use provider's 24h change directly
    if yf_quote and yf_quote.get("dayChangePct") is not None:
        day_change_pct = yf_quote["dayChangePct"]
        day_change = quantity * current_price * (day_change_pct / 100)
    else:
        day_change_pct = None
        day_change = None
else:
    # Equity: compute from prev_close with guardrails
    if prev_close and prev_close > 0:
        day_change_pct = ((current_price - prev_close) / prev_close) * 100
        day_change = (current_price - prev_close) * quantity
        if abs(day_change_pct) > 300:
            day_change_pct = None
            day_change = None
    else:
        day_change_pct = None
        day_change = None
```

### Top Movers Fix

In `GET /portfolio/movers`, filter out positions where `dayChangePercent is None` before ranking.

---

## Workstream 4: Position Aggregation

### Current State

Backend already aggregates by `(symbol, assetType)` at `portfolio.py:375-413`. This should handle most cases.

### Enhancement

Add `?lots=true` query parameter:
- Default (omitted or `lots=false`): aggregated view (current behavior)
- `lots=true`: skip merge step, return per-account rows with `accountId` visible

### Duplicate Investigation

Before implementation, run the debug endpoint for GOOGL/NVDA/AMZN to verify whether duplicates come from:
1. Different `assetType` for same symbol across accounts → fix assetType consistency
2. Frontend rendering bug (missing key prop, double-fetch) → fix in React
3. Both crypto and equity accounts holding same ticker → aggregation key includes assetType, so these stay separate (correct behavior)

---

## Workstream 5: Orders Display Cleanup

### Backend Changes (`app/routes/orders.py`)

**Default filter**: Only return `action IN ('BUY', 'SELL', 'BUY_OPEN', 'SELL_CLOSE')` unless overridden.

Add query parameters:
- `include_drip=true` — include DIVIDEND/REI reinvestment orders
- `action` — explicit filter (e.g., `action=BUY,SELL`)

**Symbol validation**: Before returning, check if `symbol` matches UUID pattern (`/^[0-9a-f]{8}-/`). If so, attempt to resolve from:
1. The order's `symbol_description` field
2. The `symbols` table via `symbol_id`
3. Fall back to "Unknown"

### Frontend Changes

**Dashboard "Recent Orders"**: Call `/api/orders?limit=5` (backend now defaults to BUY/SELL only).

**New "Dividends & DRIP" section**: Separate component on dashboard or a tab on orders page. Calls `/api/orders?include_drip=true&action=DIVIDEND,REI`.

**Per-stock page**: Add "Activity & Orders" tab showing last 20 activities + 20 orders filtered by that symbol.

---

## Workstream 6: Ideas Context Navigation

### New Backend Endpoint

`GET /ideas/{idea_id}/context`

Response:
```json
{
  "idea": { /* full IdeaOut fields */ },
  "parentMessage": {
    "id": "...",
    "content": "...",
    "author": "...",
    "sent_at": "2026-02-28T14:30:00Z",
    "channel_id": "..."
  },
  "contextMessages": [
    { "id", "content", "author", "sent_at", "is_parent": false },
    { "id", "content", "author", "sent_at", "is_parent": true },
    { "id", "content", "author", "sent_at", "is_parent": false }
  ]
}
```

**Query**: Fetch parent from `discord_messages` via `origin_message_id`, then fetch ±5 messages from same `channel_id` ordered by `created_at`.

**Timestamp audit**: Verify that `discord_messages.created_at` reflects Discord's `message.created_at` (actual send time), not insertion time.

### Frontend Changes

**IdeaDetailDrawer** enhancement:
- Add "View Context" button that fetches `/api/ideas/{id}/context`
- Shows parent message highlighted with ±5 surrounding messages
- "View in Raw" button: navigates to raw messages panel, scrolls to and highlights the parent message

---

## Workstream 7: TradingView Canonical Symbols

### Problem

Frontend currently generates TradingView symbols from raw tickers using a hardcoded exchange map. Crypto symbols are generated as `CRYPTO:${symbol}USD`, but this logic should use the canonical `tv_symbol` from the backend.

### Fix

1. **Backend**: Include `tvSymbol` in Position response (from `CRYPTO_IDENTITY` for crypto, computed from `exchange_code` + symbol for equities)

2. **Frontend `TradingViewChart.tsx`**: Replace the entire `getSymbol()` function:
   - If position has `tvSymbol` → use it directly
   - Else fallback to current exchange-mapping logic (for legacy/unmatched symbols)

3. **Equity TV symbols**: Backend computes using `exchange_code` from the `symbols` table:
   - `exchange_code == 'NASDAQ'` → `NASDAQ:AAPL`
   - `exchange_code == 'NYSE'` → `NYSE:JPM`
   - else → bare symbol (TradingView auto-detects)

---

## Implementation Priority Order

1. **Workstream 2** — Crypto price identity fix (highest impact, fixes wrong prices)
2. **Workstream 3** — Day change guardrails (fixes Top Movers)
3. **Workstream 1** — Debug endpoint (validates fixes 1-2)
4. **Workstream 7** — TradingView canonical symbols (depends on CRYPTO_IDENTITY from WS2)
5. **Workstream 4** — Position aggregation (investigate + fix duplicates)
6. **Workstream 5** — Orders display cleanup
7. **Workstream 6** — Ideas context navigation

---

## Files Changed (Estimated)

### Backend (LLM-portfolio-project)
| File | Change |
|------|--------|
| `src/market_data_service.py` | Add `CRYPTO_IDENTITY` dict, update `_yf_symbol()` |
| `app/routes/portfolio.py` | Split price lookup by asset type, add day change guards, add `lots` param, add `tvSymbol` to Position |
| `app/routes/debug.py` | New file — symbol trace endpoint |
| `app/routes/orders.py` | Default BUY/SELL filter, UUID symbol resolution |
| `app/routes/ideas.py` | New `/ideas/{id}/context` endpoint |
| `app/main.py` | Register debug routes conditionally |

### Frontend (LLM-portfolio-frontend)
| File | Change |
|------|--------|
| `src/components/stock/TradingViewChart.tsx` | Use `tvSymbol` from API instead of computing |
| `src/components/dashboard/RecentOrders.tsx` | Update to use new default filter |
| `src/components/ideas/IdeaDetailDrawer.tsx` | Add context modal + View in Raw |
| `src/types/api.ts` | Add `tvSymbol` to Position type |
| `src/app/api/ideas/[id]/context/route.ts` | New BFF route |

---

## Out of Scope

- Chat wiring (deferred until data quality is correct)
- Database schema migrations (no new columns needed — canonical symbols stored in code)
- SnapTrade collector changes (the collector is fine; the bug is in the API response layer)
- Position reconciliation changes (safety guards already exist and are adequate)
