# Stock Detail Page UX Refinement — Design Doc

**Date**: 2026-03-02
**Status**: Approved
**Scope**: Frontend (LLM-portfolio-frontend)

## Problem Statement

The stock detail page has several UX issues:
1. Tab panel is fixed-width (w-80/w-96) and cannot be resized
2. Ideas and raw messages show short snippets with no way to see surrounding Discord context
3. Trades is hidden behind a tab and shows a 404 error
4. Position data shows different numbers than the positions page (single account vs aggregated)
5. Quantity column shows floating-point noise (e.g., `1.7226000000000001`)
6. Text overflows at certain viewport sizes

## Design Decisions

### 1. Resizable Two-Panel Layout

**Library**: `react-resizable-panels` (~8KB gzipped)

**Layout**:
- `PanelGroup direction="horizontal"` with default 60/40 split
- **Left panel**: TradingView chart (top) + Trades section (bottom, always visible)
- **Right panel**: Tabbed content (Chat, Ideas, Raw, Insights, Notes)
- `PanelResizeHandle` between panels with a visible drag indicator
- Min sizes: left 30%, right 25%
- Panel sizes persist to `localStorage` key `stock-panel-sizes`
- Mobile (<1024px): stacks vertically, no resize handle, full width

```
┌─────────────────────────────────┬────────────────────────────────┐
│  TradingView Chart              │  [Chat] [Ideas] [Raw]          │
│  (provider toggle + refresh)    │  [Insights] [Notes]            │
│                                 │                                │
│                                 │  Content area (scrollable)     │
│  ◄─── drag handle ───►         │                                │
├─────────────────────────────────┤                                │
│  Trades (always visible)        │                                │
│  max-h-[250px] overflow-y-auto  │                                │
│  BUY 2.5 @ $165.20  Jan 15     │                                │
│  SELL 1.0 @ $195.00  Feb 20    │                                │
└─────────────────────────────────┴────────────────────────────────┘
```

### 2. Trades as Permanent Section (Not Tab)

- Remove `'trades'` from the `TABS` array in `StockHubContent.tsx`
- Render `<TradesPanel>` directly below the chart in the left column
- Compact one-line format: `BUY 2.5 sh @ $165.20 · Jan 15, 2025`
- `max-h-[250px] overflow-y-auto` (4-5 rows visible, scroll for more)
- If no trades: minimal "No trades recorded" text (not an error card)
- Fix the 404 by ensuring BFF route has `force-dynamic` export + graceful fallback

### 3. Inline Context Expansion for Ideas & Raw Messages

Each idea/raw message card gets a "Show context" chevron/button.

**On click**:
1. Calls `GET /api/ideas/{id}/context` (already exists)
2. Returns `parentMessage` + `contextMessages` (5 before/after from same Discord channel)
3. Expands an accordion below the idea card showing messages chronologically
4. Originating message highlighted with brighter background + left accent border
5. Each context message shows: author, timestamp, channel, full content
6. Collapse on second click
7. Loading skeleton while fetching

```
┌─ Idea ──────────────────────────────────────┐
│ ↗ Bullish 90%  FUNDAMENTAL THESIS  EARNINGS │
│ "Networking/ Spectrum X Ethernet has been…"  │
│ @qmy.y · Feb 26                              │
│                            ▼ Show context     │
│ ┌─────────────────────────────────────────┐  │
│ │ @user1 · 3:42 PM                        │  │
│ │ "What do you think about NVDA earnings?" │  │
│ ├── highlighted ──────────────────────────┤  │
│ │ ▶ @qmy.y · 3:45 PM          ← THIS MSG │  │
│ │ "Networking/ Spectrum X Ethernet has     │  │
│ │  been a homerun..."                      │  │
│ ├─────────────────────────────────────────┤  │
│ │ @user2 · 3:47 PM                        │  │
│ │ "Agree, the data center demand is..."    │  │
│ └─────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

**For Raw Messages**: Same pattern. Fetch context by message ID (may need a lightweight backend endpoint or reuse the ideas context endpoint adapted for raw message IDs).

### 4. Position Display Fixes

#### 4a. Quantity Formatting

Add `formatQuantity()` to `format.ts`:
- Whole numbers → 0 decimals (e.g., `10`)
- Fractional → up to 4 decimals, trailing zeros stripped (e.g., `1.7226`)

Apply to: `positions/page.tsx`, `HoldingsTable.tsx`, `CryptoSection.tsx`, `PositionsTable.tsx`, `PositionCard.tsx`

#### 4b. Per-Account Position Breakdown (Stock Detail Page)

Rebuild `RobinhoodPositionCard.tsx` to:
1. Fetch `/api/portfolio` and filter by ticker to get all account positions
2. Show aggregated totals at top (total shares, market value, weighted avg cost, diversity %, returns)
3. Show per-account rows below (account name, shares, value) if >1 account holds the stock
4. Skip breakdown section if only one account

```
┌─ Your Position ──────────────────────────────┐
│  Total Shares    Market Value    Diversity    │
│  9.2149          $1,632.79       8.5%         │
│  Average Cost    Today's Return               │
│  $188.46         +$0.00 (0.00%)               │
│  Total Return                                 │
│  +$505.51 (+54.68%)                           │
│  ┌─ Accounts ─────────────────────────────┐   │
│  │ Individual   8.6779 sh  $1,536.07      │   │
│  │ Roth IRA     0.5370 sh  $96.72         │   │
│  └────────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

#### 4c. Responsive Text Overflow

- Add `truncate` / `line-clamp-2` to company name columns
- Use responsive font sizes (`text-xs sm:text-sm`) for numeric columns
- Ensure `font-mono tabular-nums` on all number columns

### 5. TopMovers Hook Fix (Already Applied)

Moved `useSparklines('1M')` above early returns in `TopMovers.tsx` to fix React error #310.

## Files Affected

| # | File | Change |
|---|------|--------|
| 1 | `package.json` | Add `react-resizable-panels` |
| 2 | `StockHubContent.tsx` | Resizable panels layout, remove trades tab |
| 3 | `IdeasPanel.tsx` | Inline context accordion |
| 4 | `RawMessagesPanel.tsx` | Inline context accordion |
| 5 | `format.ts` | Add `formatQuantity()` |
| 6 | `positions/page.tsx` | Use `formatQuantity()` |
| 7 | `HoldingsTable.tsx` | Use `formatQuantity()` + text overflow |
| 8 | `CryptoSection.tsx` | Use `formatQuantity()` |
| 9 | `PositionsTable.tsx` | Use `formatQuantity()` |
| 10 | `PositionCard.tsx` | Use `formatQuantity()` |
| 11 | `RobinhoodPositionCard.tsx` | Per-account breakdown |
| 12 | `TradesPanel.tsx` | Compact format, graceful empty state |
| 13 | `activities BFF route` | Ensure `force-dynamic` export |
| 14 | `TopMovers.tsx` | Hook order fix (already done) |

## Out of Scope

- Backend API changes (all needed endpoints already exist)
- New backend endpoints for raw message context (stretch goal — assess during implementation)
- Chart provider changes (TradingView vs lightweight-charts toggle stays as-is)
- Mobile layout redesign (mobile stacks vertically, unchanged)
