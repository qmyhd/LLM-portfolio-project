# Portfolio Overhaul Design — Full Sprint

**Date**: 2026-03-02
**Status**: Approved
**Scope**: Data pipeline, API enhancements, dashboard overhaul, stock detail improvements, UI polish

---

## Overview

Comprehensive overhaul of the portfolio application addressing: data completeness (activity backfill, Discord re-parse), dashboard UX (Blossom-inspired trade cards, dual holdings tables), stock detail improvements (trades tab, date fixes, missing ideas), and UI polish (splash, login, CSS artifacts).

## Phase 1: Data Foundation (Backend)

### 1.1 Activity Backfill
- Run `scripts/backfill_activities.py --start 2020-01-01`
- Target: 415 → ~7,500 activities covering BUY, SELL, DIVIDEND, FEE records
- Each record includes: price, units, symbol, trade_date, settlement_date, amount

### 1.2 Discord Re-Ingestion
- Run `src/discord_ingest.py` to catch message gaps
- Run `scripts/nlp/parse_messages.py` to re-parse ideas from messages
- Fixes: missing ideas for SNDK and other stocks with known Discord mentions

### 1.3 Dividend Identification
- Activities with `activity_type = 'DIVIDEND'` already stored by SnapTrade
- No schema change needed — expose via API with proper labeling

### 1.4 Orders "Unknown" Fix
- Commit `86283c0` added UUID symbol guards
- Verify deployment and BFF route passes `action=BUY,SELL` filter

---

## Phase 2: Backend API Enhancements

### 2.1 Per-Stock Activities Endpoint
```
GET /stocks/{ticker}/activities?limit=50
Response: {
  activities: [{
    id, activityType, tradeDate, price, units, amount, fee,
    positionChangePct,  // calculated: how this trade changed portfolio allocation
    cumulativeQty,      // running total of shares after this trade
    realizedPnl         // for sells: (sell_price - avg_cost) * units
  }]
}
```

### 2.2 Enhanced Position Data
Add to each position in `GET /portfolio`:
- `dayChangePct` — already computed, ensure consistency
- `weekChangePct` — from yfinance 1-week return metric
- `avgCost` — already available as `averageBuyPrice`

### 2.3 Idea Date Fix
- Use `sourceCreatedAt` (actual Discord message timestamp) instead of `createdAt` (database insert time)
- Format: "Feb 25" for <30 days, "Dec 12, 2024" for older

### 2.4 Multi-Symbol Idea Lookup
- Query `discord_parsed_ideas` by both `symbol` (primary) and `symbols` (array contains)
- Fixes: stocks like SNDK that appear in `symbols[]` but not as primary

---

## Phase 3: Dashboard Overhaul (Frontend)

### 3.1 Trade Recap Cards (replaces RecentOrders)
Component: `TradeRecapCard` / `RecentTrades`

Layout per card:
- Left: action badge (▲ BUY purple/blue, ▼ SELL green/red based on P/L, ● DIV blue)
- Center: ticker @ price, quantity × shares · total
- Right: date
- Bottom: position change (e.g., "8.2% → 8.2% of portfolio")
- For sells: show % gain/loss

Card styling:
- BUY: purple/blue left border
- SELL (profit): green left border
- SELL (loss): red left border
- DIVIDEND: teal/blue left border

Data source: `GET /activities?limit=10` (most recent)

### 3.2 Daily Movers Table (new)
Component: `DailyMoversTable`

- Shows all positions sorted by day change % (descending)
- Columns: Symbol, Price, Day Δ%, Week Δ%
- Toggle between 1D and 1W sort
- Paginated at 10, "Show more" button
- Color-coded percentages (green/red)

Data source: existing `GET /portfolio` positions with enhanced day/week % fields

### 3.3 All-Time Holdings Table (enhanced HoldingsTable)
Component: `AllTimeHoldingsTable`

- Shows all positions sorted by market value (descending)
- Columns: Symbol, Market Value, P/L %, Avg Cost
- Avg cost displayed in smaller text below P/L %
- Asset type filters: All, Stocks, ETFs
- Paginated at 10
- Remove the white glow CSS artifact

### 3.4 TopMovers Redesign
- Larger % change numbers
- Mini sparkline next to each mover
- Clickable rows → stock detail page

### 3.5 CSS Fixes
- Fix white glow in HoldingsTable (box-shadow or gradient artifact)
- Fix number overflow with `tabular-nums` and proper `min-width`
- Fix PortfolioSummary card overflow on mobile

---

## Phase 4: Stock Detail + Polish

### 4.1 Trades Tab (new)
Add "Trades" tab to stock detail sidebar (after Notes):
- Shows all BUY/SELL/DIVIDEND activities for this ticker
- Uses same TradeRecapCard component from dashboard
- Each card: action, price, quantity, date, position % change
- Sorted newest-first
- Data source: `GET /stocks/{ticker}/activities`

### 4.2 Position Card Fix
- Fixed-height grid cells
- Consistent padding/font sizes
- `tabular-nums` for all monetary values
- Clean 2-row layout for returns

### 4.3 More Stats Visibility
- Default expanded on desktop, collapsed on mobile
- Label: "Stats & Fundamentals" with chevron
- Subtle divider line above

### 4.4 Message Date Fix
- Use `sourceCreatedAt` for idea display dates
- Format: "Feb 25" (recent), "Dec 12, 2024" (older)
- Show actual conversation timestamps in context view

### 4.5 QQQ Splash Polish
- Tighter letter-spacing for connected feel
- Simplify animation: clean fade-in + subtle scale, remove disconnected glow
- Consider font change: DM Serif Display or keep Inter bold

### 4.6 Sign-In Page Fix
- Remove grey box around "or continue with" divider
- Clean line with text overlay instead
- Increase QQQ text contrast against liquid gradient background

---

## Data Flow Summary

```
SnapTrade Activities API → backfill_activities.py → activities table
                                                        ↓
Discord Messages → discord_ingest.py → parse_messages.py → discord_parsed_ideas
                                                        ↓
FastAPI Backend ← GET /stocks/{ticker}/activities (new)
                ← GET /portfolio (enhanced with week%)
                ← GET /stocks/{ticker}/ideas (multi-symbol query)
                                                        ↓
Next.js BFF → Dashboard (TradeRecap, DailyMovers, AllTimeHoldings)
            → Stock Detail (Trades tab, fixed dates, position card)
```

## Files to Create/Modify

### Backend (~8 files)
- `app/routes/stocks.py` — Add activities endpoint, fix idea multi-symbol query
- `app/routes/portfolio.py` — Add weekChangePct to positions
- `app/routes/activities.py` — Enhance with position change metadata
- `app/routes/ideas.py` — Fix date field usage
- `scripts/backfill_activities.py` — Run for data backfill

### Frontend (~12 files)
- `src/components/dashboard/TradeRecap.tsx` — New: Blossom-style trade cards
- `src/components/dashboard/DailyMoversTable.tsx` — New: daily % change table
- `src/components/dashboard/HoldingsTable.tsx` — Modify: all-time P/L + avg cost
- `src/components/dashboard/TopMovers.tsx` — Enhance with sparklines
- `src/components/dashboard/RecentOrders.tsx` — Replace with TradeRecap
- `src/components/stock/TradesPanel.tsx` — New: per-stock activity history
- `src/components/stock/RobinhoodPositionCard.tsx` — Fix sizing
- `src/components/stock/StockHubContent.tsx` — Add Trades tab
- `src/components/stock/IdeasPanel.tsx` — Fix date display
- `src/components/ui/QQQSplash.tsx` — Font + animation polish
- `src/components/ui/SigninIntro.tsx` — Fix divider styling
- `src/app/page.tsx` — Dashboard layout restructure
- `src/app/api/stocks/[ticker]/activities/route.ts` — New BFF route

## Success Criteria

1. Activity feed shows ~7,500 entries (up from 415)
2. Dashboard shows trade recap cards with position % change and P/L
3. Two separate holdings tables: daily movers and all-time P/L with avg cost
4. Stock detail page has "Trades" tab with full trade history
5. Idea dates show actual Discord message timestamps
6. SNDK and similar stocks show their associated ideas
7. No "Unknown" symbols in orders
8. QQQ splash animation is clean and connected
9. Sign-in divider has no grey box
10. No white glow artifact in holdings table
11. Numbers fit cleanly in all cards/cells
