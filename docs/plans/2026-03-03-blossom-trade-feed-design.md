# Blossom-Style Activity Feed + Trade Fixes Design

**Date**: 2026-03-03
**Status**: Approved

## Problem

1. "Recent Trades" on stock pages shows "No trades found" because it only queries `activities` table, but trade data also lives in `orders` table
2. Trade cards show raw transaction data without P/L, portfolio %, or position context
3. Raw message context includes bot commands (`!fetch`, `!history`) and bot responses (`@QBOT`)
4. No historical position tracking for accurate P/L on past trades

## Solution

### 1. Unified Trade Endpoint (Backend)

**New endpoint**: `GET /stocks/{ticker}/trades` — merges orders + activities.

**Data sources**:
- `activities` table: BUY, SELL, DIVIDEND, FEE with price, units, amount, trade_date
- `orders` table: BUY, SELL with execution_price, filled_quantity, time_executed (status=EXECUTED/FILLED)

**Deduplication**: Match on `UPPER(symbol)` + `trade_date` within 60 seconds + `ABS(amount)` within $0.02. Prefer activities row when duplicated (has more metadata like fees).

**Enrichment** (per trade, from `positions` table):
- `currentPrice`: positions.current_price (or positions.price fallback)
- `avgCost`: positions.average_buy_price
- `totalShares`: positions.quantity
- `marketValue`: positions.equity
- `portfolioPct`: (positions.equity / SUM(all positions.equity)) * 100
- `unrealizedPnl`: (currentPrice - avgCost) * totalShares (for BUY)
- `realizedPnl`: (salePrice - avgCost) * units (for SELL)
- `positionChangePct`: delta in portfolio allocation from this trade

**Account filtering**: JOIN `accounts` table, exclude `connection_status = 'deleted'`.

**Dashboard endpoint**: `GET /trades/recent?limit=10` — same logic, no ticker filter.

### 2. Blossom-Style Trade Cards (Frontend)

Replace `TradeCard` in TradesPanel and `ActivityRow` in TradeRecap with `BlossomTradeCard`.

**BUY card layout**:
```
┌───────────────────────────────────────────┐
│  BUY  NVDA                       Mar 3    │
│  Bought 0.076 shares @ $186.30            │
│  Total: $14.26                            │
│  ┌────────────┐  ┌─────────────┐          │
│  │ Portfolio   │  │ Position    │          │
│  │ 7.9%       │  │ +$384.60    │          │
│  │             │  │ +126.0%     │          │
│  └────────────┘  └─────────────┘          │
└───────────────────────────────────────────┘
```

**SELL card layout** (gain = green border, loss = red border):
```
┌───────────────────────────────────────────┐
│  SELL  SMST                      Feb 3    │
│  Sold 4 shares @ $111.41                  │
│  Realized: +$280.50 (+155.6%)             │
│  ┌────────────┐  ┌─────────────┐          │
│  │ Portfolio   │  │ Avg Cost    │          │
│  │ ↓ 5%       │  │ $43.60      │          │
│  │             │  │ → $111.41   │          │
│  └────────────┘  └─────────────┘          │
└───────────────────────────────────────────┘
```

**Colors**: BUY=indigo, SELL+gain=profit, SELL+loss=loss, DIVIDEND=blue.
Use existing `pnlTextColor()`, `pnlBgColor()` from `lib/colors.ts`.

### 3. Context Filtering (Backend)

Modify `get_stock_idea_context()` in `app/routes/stocks.py`:
- Filter `WHERE author NOT IN ('QBOT', 'QBot')` from context query
- Filter `WHERE content NOT LIKE '!%' AND content NOT LIKE '/%'` (bot commands)
- Filter `WHERE LENGTH(content) >= 5` (trivial messages)
- Apply filters in the SQL UNION subqueries before LIMIT

### 4. Position Snapshots Table

**New migration** `068_position_snapshots.sql`:
```sql
CREATE TABLE public.position_snapshots (
  id SERIAL PRIMARY KEY,
  account_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  snapshot_date DATE NOT NULL,
  quantity NUMERIC(15,4),
  average_buy_price NUMERIC(12,4),
  current_price NUMERIC(12,4),
  equity NUMERIC(15,4),
  total_portfolio_value NUMERIC(15,4),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(account_id, symbol, snapshot_date)
);
CREATE INDEX idx_position_snapshots_symbol_date ON position_snapshots(symbol, snapshot_date DESC);
CREATE INDEX idx_position_snapshots_account_date ON position_snapshots(account_id, snapshot_date DESC);
ALTER TABLE position_snapshots ENABLE ROW LEVEL SECURITY;
```

**Nightly pipeline**: After `sync_snaptrade_data()`, snapshot all current positions:
```python
INSERT INTO position_snapshots (account_id, symbol, snapshot_date, quantity, average_buy_price, current_price, equity, total_portfolio_value)
SELECT p.account_id, p.symbol, CURRENT_DATE, p.quantity, p.average_buy_price,
       COALESCE(p.current_price, p.price), p.equity,
       (SELECT SUM(equity) FROM positions WHERE account_id IN (SELECT id FROM accounts WHERE connection_status != 'deleted'))
FROM positions p
JOIN accounts a ON a.id = p.account_id AND a.connection_status != 'deleted'
ON CONFLICT (account_id, symbol, snapshot_date) DO UPDATE SET
  quantity = EXCLUDED.quantity, average_buy_price = EXCLUDED.average_buy_price,
  current_price = EXCLUDED.current_price, equity = EXCLUDED.equity,
  total_portfolio_value = EXCLUDED.total_portfolio_value;
```

**P/L lookup**: For a trade on date D, find `position_snapshots WHERE symbol = X AND snapshot_date <= D ORDER BY snapshot_date DESC LIMIT 1`. Fallback to current `positions.average_buy_price` if no snapshot exists.

### 5. Frontend API + Hook Changes

**New BFF route**: `GET /api/trades?ticker={ticker}&limit=10` → FastAPI `/stocks/{ticker}/trades` or `/trades/recent`
**New hook**: `useEnrichedTrades(ticker?, limit?)` — SWR wrapper
**New type**: `EnrichedTrade` in `types/api.ts`

### 6. Files to Create/Modify

**Backend (LLM-portfolio-project)**:
- `app/routes/trades.py` — New route file with unified trade endpoints
- `app/routes/stocks.py` — Modify context endpoint for filtering
- `app/main.py` — Register trades router
- `schema/068_position_snapshots.sql` — New migration
- `scripts/nightly_pipeline.py` — Add snapshot step

**Frontend (LLM-portfolio-frontend)**:
- `src/components/trade/BlossomTradeCard.tsx` — New component
- `src/components/stock/TradesPanel.tsx` — Use new data source + BlossomTradeCard
- `src/components/dashboard/TradeRecap.tsx` — Use new data source + BlossomTradeCard
- `src/app/api/trades/route.ts` — New BFF proxy
- `src/app/api/stocks/[ticker]/trades/route.ts` — New BFF proxy
- `src/hooks/useEnrichedTrades.ts` — New SWR hook
- `src/types/api.ts` — Add EnrichedTrade type
