# Portfolio Overhaul Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Comprehensive portfolio overhaul — backfill data, enhance APIs, redesign dashboard with Blossom-style trade cards and dual holdings tables, add per-stock trade history, and polish UI.

**Architecture:** Data-first approach: Phase 1 backfills activities and re-parses Discord ideas. Phase 2 adds backend API endpoints for per-stock activities and enhanced position data. Phase 3 replaces the dashboard's RecentOrders with trade recap cards and adds dual holdings tables. Phase 4 adds a Trades tab to stock detail, fixes position card, dates, splash, and login UI.

**Tech Stack:** Python/FastAPI (backend), Next.js 14/TypeScript (frontend), SWR (data fetching), Tailwind CSS, anime.js (animations)

**Repos:**
- Backend: `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project\`
- Frontend: `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend\`

---

## Phase 1: Data Foundation

### Task 1: Backfill SnapTrade Activities

**Files:**
- Run: `scripts/backfill_activities.py`

**Step 1: Check current activity count**

```bash
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project
python -c "from src.db import execute_sql; rows = execute_sql('SELECT COUNT(*) as cnt FROM activities', fetch_results=True); print(f'Current activities: {rows[0][\"cnt\"]}')"
```

Expected: ~415 activities

**Step 2: Run the backfill**

```bash
python scripts/backfill_activities.py --start 2020-01-01
```

Expected: Script fetches SnapTrade activities and upserts into `activities` table. Target: ~7,500 records.

**Step 3: Verify the backfill**

```bash
python -c "from src.db import execute_sql; rows = execute_sql('SELECT activity_type, COUNT(*) as cnt FROM activities GROUP BY activity_type ORDER BY cnt DESC', fetch_results=True); [print(f'{r[\"activity_type\"]}: {r[\"cnt\"]}') for r in rows]"
```

Expected: BUY, SELL, DIVIDEND, FEE categories with significantly more records.

**Step 4: Commit — no code changes, data-only operation**

No git commit needed — this is a data backfill on the production database.

---

### Task 2: Re-Ingest Discord Messages and Re-Parse Ideas

**Files:**
- Run: `src/discord_ingest.py`
- Run: `scripts/nlp/parse_messages.py`

**Step 1: Run Discord ingestion to catch message gaps**

```bash
python -m src.discord_ingest
```

Expected: Fetches any Discord messages not yet in `discord_messages` table.

**Step 2: Re-parse ideas from messages**

```bash
python scripts/nlp/parse_messages.py
```

Expected: Re-processes unparsed messages through NLP pipeline, creating new `discord_parsed_ideas` entries. Should pick up SNDK and other missing stock mentions.

**Step 3: Verify SNDK ideas exist**

```bash
python -c "from src.db import execute_sql; rows = execute_sql(\"SELECT COUNT(*) as cnt FROM discord_parsed_ideas WHERE 'SNDK' = ANY(symbols) OR symbol = 'SNDK'\", fetch_results=True); print(f'SNDK ideas: {rows[0][\"cnt\"]}')"
```

Expected: At least 1 SNDK idea.

---

## Phase 2: Backend API Enhancements

### Task 3: Add Per-Stock Activities Endpoint

**Files:**
- Modify: `app/routes/stocks.py` (add new endpoint after line 645)
- Test: Manual API test

**Step 1: Add Activity models to stocks.py**

Add after the `OHLCVSeries` model (around line 176):

```python
class StockActivity(BaseModel):
    """Activity record for a specific stock."""
    id: str
    activityType: Optional[str] = None
    tradeDate: Optional[str] = None
    price: Optional[float] = None
    units: Optional[float] = None
    amount: float = 0.0
    fee: float = 0.0
    description: Optional[str] = None

class StockActivitiesResponse(BaseModel):
    """Activities for a specific stock."""
    ticker: str
    activities: list[StockActivity]
    total: int
```

**Step 2: Add the endpoint**

Add after the `get_ohlcv` endpoint (end of file):

```python
@router.get("/{ticker}/activities", response_model=StockActivitiesResponse)
async def get_stock_activities(
    ticker: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Get trade and dividend activity history for a specific stock."""
    clean = _validate_ticker(ticker)

    try:
        count_q = """
            SELECT COUNT(*) as cnt
            FROM activities
            WHERE UPPER(symbol) = UPPER(:ticker)
        """
        count_rows = execute_sql(count_q, params={"ticker": clean}, fetch_results=True)
        total = int(count_rows[0]["cnt"]) if count_rows else 0

        query = """
            SELECT id, activity_type, trade_date, price, units, amount, fee, description
            FROM activities
            WHERE UPPER(symbol) = UPPER(:ticker)
            ORDER BY trade_date DESC, created_at DESC
            LIMIT :limit OFFSET :offset
        """
        rows = execute_sql(query, params={"ticker": clean, "limit": limit, "offset": offset}, fetch_results=True) or []

        activities = []
        for r in rows:
            row = dict(r) if not isinstance(r, dict) else r
            activities.append(StockActivity(
                id=str(row.get("id", "")),
                activityType=row.get("activity_type"),
                tradeDate=str(row["trade_date"]) if row.get("trade_date") else None,
                price=safe_float_optional(row.get("price")),
                units=safe_float_optional(row.get("units")),
                amount=safe_float(row.get("amount")),
                fee=safe_float(row.get("fee")),
                description=row.get("description"),
            ))

        return StockActivitiesResponse(ticker=clean, activities=activities, total=total)

    except Exception as e:
        logger.error(f"Error fetching activities for {clean}: {e}", exc_info=True)
        return StockActivitiesResponse(ticker=clean, activities=[], total=0)
```

**Step 3: Add missing imports to stocks.py**

Ensure these imports exist at the top of `stocks.py`:

```python
import math
```

And add the `safe_float` / `safe_float_optional` helpers (copy from activities.py):

```python
def safe_float(value, default=0.0):
    if value is None: return default
    try:
        f = float(value)
        return default if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return default

def safe_float_optional(value):
    if value is None: return None
    try:
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None
```

**Step 4: Test the endpoint**

```bash
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project
python -c "
import uvicorn
# Quick smoke test - start server and call endpoint
"
# Or use curl against running server:
# curl -H 'Authorization: Bearer <token>' http://localhost:8000/stocks/NVDA/activities?limit=5
```

**Step 5: Commit**

```bash
git add app/routes/stocks.py
git commit -m "feat: add per-stock activities endpoint GET /stocks/{ticker}/activities"
```

---

### Task 4: Fix Ideas Multi-Symbol Query

**Files:**
- Modify: `app/routes/stocks.py:413-521` (the `get_stock_ideas` endpoint)

**Step 1: Update the ideas query to search both `symbol` and `symbols` array**

In the `get_stock_ideas` endpoint, find the WHERE clause that filters by symbol. Change it from:

```sql
WHERE dpi.symbol = UPPER(:ticker)
```

To:

```sql
WHERE (dpi.symbol = UPPER(:ticker) OR UPPER(:ticker) = ANY(dpi.symbols))
```

This ensures stocks like SNDK that appear in the `symbols[]` array but not as the primary `symbol` are found.

**Step 2: Also update the count query with the same WHERE clause change**

**Step 3: Test with SNDK**

```bash
curl -H 'Authorization: Bearer <token>' http://localhost:8000/stocks/SNDK/ideas
```

Expected: Returns ideas where SNDK appears in either `symbol` or `symbols[]`.

**Step 4: Commit**

```bash
git add app/routes/stocks.py
git commit -m "fix: search ideas by both primary symbol and symbols array"
```

---

### Task 5: Add weekChangePct to Portfolio Positions

**Files:**
- Modify: `app/routes/portfolio.py:67-87` (Position model)
- Modify: `app/routes/portfolio.py:142-605` (get_portfolio endpoint)

**Step 1: Add `weekChangePct` field to the Position model**

In `portfolio.py`, find the `Position` model and add:

```python
weekChangePct: Optional[float] = None
```

**Step 2: In the portfolio endpoint, compute week change from yfinance return metrics**

After the day change calculation loop, add a batch call to `get_return_metrics` from `market_data_service` for each symbol, and set `weekChangePct` from the `return1wPct` value. This data is already fetched via yfinance in the price cascade — just needs to be surfaced.

Look for where `dayChangePercent` is set in the position building loop and add:

```python
# Week change from return metrics
try:
    from src.market_data_service import get_return_metrics
    metrics = get_return_metrics(symbol)
    if metrics:
        pos_dict["weekChangePct"] = r4n(metrics.get("return1wPct"))
except Exception:
    pass
```

**Step 3: Test**

```bash
curl -H 'Authorization: Bearer <token>' 'http://localhost:8000/portfolio' | python -m json.tool | head -50
```

Expected: Each position now includes `weekChangePct` field.

**Step 4: Commit**

```bash
git add app/routes/portfolio.py
git commit -m "feat: add weekChangePct to portfolio positions from yfinance return metrics"
```

---

## Phase 3: Dashboard Overhaul (Frontend)

### Task 6: Add Activity Type to TypeScript Types

**Files:**
- Modify: `frontend/src/types/api.ts`

**Step 1: Add StockActivity and StockActivitiesResponse types**

After the `ActivitiesResponse` type (line 404), add:

```typescript
export interface StockActivity {
  id: string;
  activityType: string | null;
  tradeDate: string | null;
  price: number | null;
  units: number | null;
  amount: number;
  fee: number;
  description: string | null;
}

export interface StockActivitiesResponse {
  ticker: string;
  activities: StockActivity[];
  total: number;
}
```

**Step 2: Add weekChangePct to Position type**

In the `Position` interface (line 31-48), add:

```typescript
weekChangePct?: number | null;
```

**Step 3: Commit**

```bash
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend
git add frontend/src/types/api.ts
git commit -m "feat: add StockActivity types and weekChangePct to Position"
```

---

### Task 7: Create BFF Route for Stock Activities

**Files:**
- Create: `frontend/src/app/api/stocks/[ticker]/activities/route.ts`

**Step 1: Create the BFF proxy route**

```typescript
import { NextRequest, NextResponse } from 'next/server';
import { getServerSession } from 'next-auth';
import { authOptions } from '@/app/api/auth/[...nextauth]/authOptions';

const API = process.env.BACKEND_URL || 'http://localhost:8000';

export async function GET(
  req: NextRequest,
  { params }: { params: { ticker: string } },
) {
  const session = await getServerSession(authOptions);
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });

  const { searchParams } = new URL(req.url);
  const limit = searchParams.get('limit') || '50';
  const offset = searchParams.get('offset') || '0';

  const url = `${API}/stocks/${params.ticker}/activities?limit=${limit}&offset=${offset}`;

  try {
    const res = await fetch(url, {
      headers: {
        Authorization: `Bearer ${process.env.API_SECRET_TOKEN}`,
        'Content-Type': 'application/json',
      },
    });

    if (!res.ok) {
      return NextResponse.json(
        { error: `Backend error: ${res.status}` },
        { status: res.status },
      );
    }

    const data = await res.json();
    return NextResponse.json(data);
  } catch (err) {
    console.error(`[stock-activities] Error:`, err);
    return NextResponse.json({ error: 'Failed to fetch activities' }, { status: 502 });
  }
}
```

**Step 2: Commit**

```bash
git add frontend/src/app/api/stocks/\[ticker\]/activities/route.ts
git commit -m "feat: add BFF proxy route for per-stock activities"
```

---

### Task 8: Create useStockActivities Hook

**Files:**
- Create: `frontend/src/hooks/useStockActivities.ts`

**Step 1: Create the SWR hook**

```typescript
import useSWR from 'swr';
import type { StockActivitiesResponse } from '@/types/api';

const fetcher = async (url: string): Promise<StockActivitiesResponse> => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch stock activities (${res.status})`);
  return res.json();
};

export function useStockActivities(ticker: string, limit = 50) {
  const { data, error, isLoading } = useSWR<StockActivitiesResponse>(
    `/api/stocks/${ticker}/activities?limit=${limit}`,
    fetcher,
    { revalidateOnFocus: false, dedupingInterval: 30000 },
  );

  return { data, error, isLoading };
}
```

**Step 2: Export from hooks index**

In `frontend/src/hooks/index.ts`, add:

```typescript
export { useStockActivities } from './useStockActivities';
```

**Step 3: Commit**

```bash
git add frontend/src/hooks/useStockActivities.ts frontend/src/hooks/index.ts
git commit -m "feat: add useStockActivities hook for per-stock trade history"
```

---

### Task 9: Create TradeRecap Component (Replaces RecentOrders)

**Files:**
- Create: `frontend/src/components/dashboard/TradeRecap.tsx`
- Modify: `frontend/src/app/page.tsx:51` (swap RecentOrders → TradeRecap)

**Step 1: Create the TradeRecap component**

```typescript
'use client';

import { clsx } from 'clsx';
import Link from 'next/link';
import { useActivities } from '@/hooks/useActivities';
import { formatMoney, formatDate } from '@/lib/format';
import { CardSpotlight } from '@/components/ui/CardSpotlight';
import type { Activity } from '@/types/api';

function TradeCard({ activity }: { activity: Activity }) {
  const isBuy = activity.activityType === 'BUY';
  const isSell = activity.activityType === 'SELL';
  const isDividend = activity.activityType === 'DIVIDEND';

  const borderColor = isDividend
    ? 'border-l-blue-500'
    : isBuy
    ? 'border-l-indigo-500'
    : activity.amount > 0
    ? 'border-l-profit'
    : 'border-l-loss';

  const actionLabel = isDividend ? 'DIV' : activity.activityType ?? 'OTHER';
  const actionIcon = isDividend ? '●' : isBuy ? '▲' : '▼';

  const actionBadgeColor = isDividend
    ? 'bg-blue-500/20 text-blue-400'
    : isBuy
    ? 'bg-indigo-500/20 text-indigo-400'
    : activity.amount > 0
    ? 'bg-profit/20 text-profit'
    : 'bg-loss/20 text-loss';

  return (
    <div
      className={clsx(
        'border-l-3 pl-4 pr-4 py-3 hover:bg-background-tertiary/50 transition-colors',
        borderColor,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span
              className={clsx(
                'inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold',
                actionBadgeColor,
              )}
            >
              {actionIcon} {actionLabel}
            </span>
            {activity.symbol ? (
              <Link
                href={`/stock/${activity.symbol}`}
                className="font-mono font-semibold text-sm hover:text-primary transition-colors"
              >
                {activity.symbol}
              </Link>
            ) : (
              <span className="text-sm text-foreground-muted">—</span>
            )}
            {activity.price != null && !isDividend && (
              <span className="text-xs text-foreground-muted">
                @ {formatMoney(activity.price)}
              </span>
            )}
          </div>

          {/* Details line */}
          <div className="text-xs text-foreground-muted">
            {isDividend ? (
              <span>{formatMoney(Math.abs(activity.amount))} dividend received</span>
            ) : (
              <>
                {activity.units != null && (
                  <span>{activity.units} shares</span>
                )}
                {activity.amount !== 0 && (
                  <span> · {formatMoney(Math.abs(activity.amount))}</span>
                )}
              </>
            )}
          </div>
        </div>

        {/* Date */}
        <span className="text-xs text-foreground-subtle whitespace-nowrap">
          {activity.tradeDate ? formatDate(activity.tradeDate, 'short') : '—'}
        </span>
      </div>
    </div>
  );
}

export function TradeRecap() {
  const { data, error, isLoading } = useActivities({ limit: 10 });

  if (isLoading) {
    return (
      <CardSpotlight className="card overflow-hidden animate-pulse">
        <div className="px-5 py-4 border-b border-border flex justify-between">
          <div className="h-5 w-28 bg-background-hover rounded" />
          <div className="h-5 w-16 bg-background-hover rounded" />
        </div>
        <div className="p-4 space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-14 bg-background-hover rounded" />
          ))}
        </div>
      </CardSpotlight>
    );
  }

  if (error) {
    return (
      <CardSpotlight className="card p-6 text-center">
        <p className="text-loss font-medium">Failed to load trades</p>
        <p className="text-sm text-foreground-muted mt-1">{error.message}</p>
      </CardSpotlight>
    );
  }

  const activities = data?.activities ?? [];

  if (activities.length === 0) {
    return (
      <CardSpotlight className="card p-6 text-center">
        <p className="text-foreground-muted">No recent trades</p>
      </CardSpotlight>
    );
  }

  return (
    <CardSpotlight className="card overflow-hidden">
      <div className="flex items-center justify-between px-5 py-4 border-b border-border">
        <h2 className="text-lg font-semibold">Recent Trades</h2>
        <Link
          href="/activity"
          className="text-sm text-primary hover:text-primary-hover transition-colors"
        >
          View All →
        </Link>
      </div>
      <div className="divide-y divide-border">
        {activities.map((activity) => (
          <TradeCard key={activity.id} activity={activity} />
        ))}
      </div>
    </CardSpotlight>
  );
}
```

**Step 2: Check if useActivities hook exists and accepts a limit param**

Read `frontend/src/hooks/useActivities.ts` and verify it supports `{ limit: 10 }`. If it doesn't accept options, update it to match the pattern in `useOrders.ts`.

**Step 3: Update dashboard page to use TradeRecap**

In `frontend/src/app/page.tsx`, replace:
- Line 8: `import { RecentOrders } from '@/components/dashboard/RecentOrders';`
  → `import { TradeRecap } from '@/components/dashboard/TradeRecap';`
- Line 51: `<RecentOrders />`
  → `<TradeRecap />`

**Step 4: Build and verify**

```bash
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend
npm run build
```

Expected: Build succeeds with no errors.

**Step 5: Commit**

```bash
git add frontend/src/components/dashboard/TradeRecap.tsx frontend/src/app/page.tsx
git commit -m "feat: replace RecentOrders with Blossom-style TradeRecap cards"
```

---

### Task 10: Create DailyMoversTable Component

**Files:**
- Create: `frontend/src/components/dashboard/DailyMoversTable.tsx`
- Modify: `frontend/src/app/page.tsx` (add to layout)

**Step 1: Create the DailyMoversTable component**

```typescript
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { clsx } from 'clsx';
import { usePortfolio } from '@/hooks/usePortfolio';
import { formatMoney, formatSignedPct } from '@/lib/format';
import { pnlTextColor } from '@/lib/colors';
import { CardSpotlight } from '@/components/ui/CardSpotlight';
import type { Position } from '@/types/api';

type SortMode = 'day' | 'week';

export function DailyMoversTable() {
  const { data, error, isLoading } = usePortfolio();
  const [sortMode, setSortMode] = useState<SortMode>('day');
  const [showAll, setShowAll] = useState(false);

  if (isLoading) {
    return (
      <CardSpotlight className="card overflow-hidden animate-pulse">
        <div className="px-5 py-4 border-b border-border">
          <div className="h-5 w-32 bg-background-hover rounded" />
        </div>
        <div className="p-4 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-8 bg-background-hover rounded" />
          ))}
        </div>
      </CardSpotlight>
    );
  }

  if (error || !data) {
    return (
      <CardSpotlight className="card p-6 text-center">
        <p className="text-loss font-medium">Failed to load movers</p>
      </CardSpotlight>
    );
  }

  // Filter out positions without valid change data and sort
  const positions = [...(data.positions ?? [])].filter(
    (p) => p.dayChangePercent != null && p.equity > 0,
  );

  positions.sort((a, b) => {
    const aVal = sortMode === 'day'
      ? Math.abs(a.dayChangePercent ?? 0)
      : Math.abs((a as any).weekChangePct ?? a.dayChangePercent ?? 0);
    const bVal = sortMode === 'day'
      ? Math.abs(b.dayChangePercent ?? 0)
      : Math.abs((b as any).weekChangePct ?? b.dayChangePercent ?? 0);
    return bVal - aVal;
  });

  const displayPositions = showAll ? positions : positions.slice(0, 10);

  return (
    <CardSpotlight className="card overflow-hidden">
      <div className="flex items-center justify-between px-5 py-4 border-b border-border">
        <h2 className="text-lg font-semibold">Daily Movers</h2>
        <div className="flex gap-1">
          {(['day', 'week'] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => setSortMode(mode)}
              className={clsx(
                'px-2.5 py-1 text-xs font-medium rounded-md transition-colors',
                sortMode === mode
                  ? 'bg-primary/20 text-primary'
                  : 'text-foreground-muted hover:text-foreground hover:bg-background-tertiary',
              )}
            >
              {mode === 'day' ? '1D' : '1W'}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border bg-background-tertiary">
              <th className="table-header text-left">Symbol</th>
              <th className="table-header text-right">Price</th>
              <th className="table-header text-right">Day %</th>
              <th className="table-header text-right hidden sm:table-cell">Week %</th>
            </tr>
          </thead>
          <tbody>
            {displayPositions.map((pos, i) => (
              <tr
                key={pos.symbol}
                className="table-row stagger-fade-in"
                style={{ '--stagger-index': i } as React.CSSProperties}
              >
                <td className="table-cell">
                  <Link
                    href={`/stock/${pos.symbol}`}
                    className="font-mono font-semibold text-sm hover:text-primary transition-colors"
                  >
                    {pos.symbol}
                  </Link>
                </td>
                <td className="table-cell text-right font-mono text-sm tabular-nums">
                  {formatMoney(pos.currentPrice)}
                </td>
                <td className={clsx('table-cell text-right font-mono text-sm font-medium tabular-nums', pnlTextColor(pos.dayChangePercent ?? 0))}>
                  {formatSignedPct(pos.dayChangePercent)}
                </td>
                <td className={clsx('table-cell text-right font-mono text-sm tabular-nums hidden sm:table-cell', pnlTextColor((pos as any).weekChangePct ?? 0))}>
                  {(pos as any).weekChangePct != null
                    ? formatSignedPct((pos as any).weekChangePct)
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {positions.length > 10 && (
        <div className="flex items-center justify-between px-5 py-3 border-t border-border text-sm">
          <span className="text-foreground-muted">
            {displayPositions.length} of {positions.length}
          </span>
          <button
            onClick={() => setShowAll(!showAll)}
            className="text-primary hover:text-primary-hover transition-colors font-medium"
          >
            {showAll ? 'Show less' : 'Show more'}
          </button>
        </div>
      )}
    </CardSpotlight>
  );
}
```

**Step 2: Update dashboard layout**

In `frontend/src/app/page.tsx`, add import:
```typescript
import { DailyMoversTable } from '@/components/dashboard/DailyMoversTable';
```

Add `<DailyMoversTable />` before the current HoldingsTable (line 56):
```tsx
<DailyMoversTable />
<HoldingsTable />
```

**Step 3: Build and verify**

```bash
npm run build
```

**Step 4: Commit**

```bash
git add frontend/src/components/dashboard/DailyMoversTable.tsx frontend/src/app/page.tsx
git commit -m "feat: add DailyMoversTable with 1D/1W sort toggle above holdings"
```

---

### Task 11: Enhance HoldingsTable with Avg Cost Column

**Files:**
- Modify: `frontend/src/components/dashboard/HoldingsTable.tsx`

**Step 1: Add avgCost below P/L % in the table**

In the HoldingsTable, find the P/L % column cell and add the average cost below it. Look for where `openPnlPercent` is rendered and add a second line:

```tsx
<td className="table-cell text-right">
  <span className={clsx('font-mono text-sm font-medium tabular-nums', pnlTextColor(pos.openPnlPercent))}>
    {formatSignedPct(pos.openPnlPercent)}
  </span>
  <div className="text-2xs text-foreground-subtle font-mono tabular-nums">
    {formatMoney(pos.averageBuyPrice)}
  </div>
</td>
```

**Step 2: Fix the white glow artifact**

Search for any `box-shadow`, `ring`, or gradient that creates a white glow on the HoldingsTable or its parent CardSpotlight. The CardSpotlight component likely has a radial gradient or spotlight effect — check if it's bleeding into the table area and tone it down or remove it for table cards.

**Step 3: Add `tabular-nums` to all numeric cells**

Ensure all `font-mono` cells also have `tabular-nums` for proper number alignment.

**Step 4: Build and verify**

```bash
npm run build
```

**Step 5: Commit**

```bash
git add frontend/src/components/dashboard/HoldingsTable.tsx
git commit -m "feat: add avg cost under P/L%, fix white glow, tabular-nums alignment"
```

---

### Task 12: Enhance TopMovers with Sparklines

**Files:**
- Modify: `frontend/src/components/dashboard/TopMovers.tsx`

**Step 1: Import MiniSparkline and sparkline data**

Add to imports:
```typescript
import { MiniSparkline } from '@/components/ui/MiniSparkline';
import { useSparklines } from '@/hooks/useSparklines';
```

**Step 2: Fetch sparkline data for mover symbols**

Inside the component, after getting the movers data:
```typescript
const moverSymbols = [...gainers, ...losers].map((p) => p.symbol);
const { data: sparkData } = useSparklines(moverSymbols);
```

**Step 3: Add sparkline next to each mover row**

In each mover row, add a small sparkline:
```tsx
<div className="w-16 h-6 flex-shrink-0">
  <MiniSparkline
    data={sparkData?.sparklines?.find((s) => s.symbol === pos.symbol)?.closes ?? []}
    color={isGainer ? '#3ba55d' : '#ed4245'}
  />
</div>
```

**Step 4: Make rows clickable**

Wrap each mover row in a `<Link href={/stock/${pos.symbol}}>`.

**Step 5: Build and verify**

```bash
npm run build
```

**Step 6: Commit**

```bash
git add frontend/src/components/dashboard/TopMovers.tsx
git commit -m "feat: add sparklines and clickable links to TopMovers"
```

---

### Task 13: Fix Dashboard Layout — Two-Column Structure

**Files:**
- Modify: `frontend/src/app/page.tsx`

**Step 1: Restructure the dashboard layout**

The final dashboard layout should be:

```tsx
{/* Portfolio Header */}
<RobinhoodHeader />
<PortfolioSummary />

{/* Trade Recap */}
<TradeRecap />

{/* Daily Movers Table (full width) */}
<DailyMoversTable />

{/* Two column: Holdings + Sidebar */}
<div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
  <div className="lg:col-span-2 space-y-6">
    <HoldingsTable />
    <CryptoSection />
  </div>
  <div className="space-y-6">
    <TopMovers />
    <SentimentOverview />
  </div>
</div>
```

**Step 2: Build and verify**

```bash
npm run build
```

**Step 3: Commit**

```bash
git add frontend/src/app/page.tsx
git commit -m "refactor: restructure dashboard layout with trade recap and daily movers"
```

---

## Phase 4: Stock Detail + Polish

### Task 14: Add Trades Tab to Stock Detail

**Files:**
- Create: `frontend/src/components/stock/TradesPanel.tsx`
- Modify: `frontend/src/components/stock/StockHubContent.tsx:25-33` (add tab)

**Step 1: Create TradesPanel component**

```typescript
'use client';

import { clsx } from 'clsx';
import { useStockActivities } from '@/hooks/useStockActivities';
import { formatMoney, formatDate } from '@/lib/format';
import type { StockActivity } from '@/types/api';

function ActivityCard({ activity }: { activity: StockActivity }) {
  const isBuy = activity.activityType === 'BUY';
  const isDividend = activity.activityType === 'DIVIDEND';

  const borderColor = isDividend
    ? 'border-l-blue-500'
    : isBuy
    ? 'border-l-indigo-500'
    : activity.amount > 0
    ? 'border-l-profit'
    : 'border-l-loss';

  const actionLabel = isDividend ? 'DIV' : activity.activityType ?? '—';
  const actionIcon = isDividend ? '●' : isBuy ? '▲' : '▼';
  const badgeColor = isDividend
    ? 'bg-blue-500/20 text-blue-400'
    : isBuy
    ? 'bg-indigo-500/20 text-indigo-400'
    : activity.amount > 0
    ? 'bg-profit/20 text-profit'
    : 'bg-loss/20 text-loss';

  return (
    <div className={clsx('border-l-3 pl-3 pr-3 py-3', borderColor)}>
      <div className="flex items-center justify-between mb-1">
        <span className={clsx('inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold', badgeColor)}>
          {actionIcon} {actionLabel}
        </span>
        <span className="text-xs text-foreground-subtle">
          {activity.tradeDate ? formatDate(activity.tradeDate, 'short') : '—'}
        </span>
      </div>
      <div className="text-xs text-foreground-muted">
        {isDividend ? (
          <span>{formatMoney(Math.abs(activity.amount))} received</span>
        ) : (
          <>
            {activity.units != null && <span>{activity.units} shares</span>}
            {activity.price != null && <span> @ {formatMoney(activity.price)}</span>}
            {activity.amount !== 0 && (
              <span className="ml-1">· {formatMoney(Math.abs(activity.amount))}</span>
            )}
          </>
        )}
      </div>
    </div>
  );
}

interface TradesPanelProps {
  ticker: string;
}

export function TradesPanel({ ticker }: TradesPanelProps) {
  const { data, error, isLoading } = useStockActivities(ticker, 100);

  if (isLoading) {
    return (
      <div className="p-4 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="skeleton h-14 rounded-lg" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-center">
        <p className="text-loss text-sm">Failed to load trades</p>
      </div>
    );
  }

  const activities = data?.activities ?? [];

  if (activities.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center p-8 text-center">
        <p className="text-foreground-muted text-sm font-medium">No trades found</p>
        <p className="text-foreground-subtle text-xs mt-1">
          Trade history for {ticker} will appear here
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto max-h-full">
      <div className="divide-y divide-border">
        {activities.map((activity) => (
          <ActivityCard key={activity.id} activity={activity} />
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Add Trades tab to StockHubContent**

In `StockHubContent.tsx`:

Add import:
```typescript
import { TradesPanel } from './TradesPanel';
```

Update TABS array (line 27-33):
```typescript
const TABS: { key: TabKey; label: string }[] = [
  { key: 'chat', label: 'Chat' },
  { key: 'ideas', label: 'Ideas' },
  { key: 'raw', label: 'Raw' },
  { key: 'insights', label: 'Insights' },
  { key: 'notes', label: 'Notes' },
  { key: 'trades', label: 'Trades' },
];
```

Update TabKey type (line 25):
```typescript
type TabKey = 'chat' | 'ideas' | 'raw' | 'insights' | 'notes' | 'trades';
```

Add tab content (after line 258):
```tsx
{activeTab === 'trades' && (
  <TradesPanel ticker={ticker} key={`trades-${refreshKey}`} />
)}
```

**Step 3: Build and verify**

```bash
npm run build
```

**Step 4: Commit**

```bash
git add frontend/src/components/stock/TradesPanel.tsx frontend/src/components/stock/StockHubContent.tsx
git commit -m "feat: add Trades tab to stock detail with per-stock activity history"
```

---

### Task 15: Fix IdeasPanel Date Display

**Files:**
- Modify: `frontend/src/components/stock/IdeasPanel.tsx:277`

**Step 1: Fix the date display in IdeaCard**

The IdeaCard currently uses `formatRelativeTime(idea.sourceCreatedAt)` (line 277). This shows "4d ago" which becomes inaccurate over time. Change to use `formatDate`:

Replace:
```tsx
<span className="text-xs text-foreground-subtle">{formatRelativeTime(idea.sourceCreatedAt)}</span>
```

With:
```tsx
<span className="text-xs text-foreground-subtle">{formatDate(idea.sourceCreatedAt, 'short')}</span>
```

This will show "Feb 25" for recent dates and "Dec 12, 2024" for older ones — matching the actual Discord message timestamp.

**Step 2: Commit**

```bash
git add frontend/src/components/stock/IdeasPanel.tsx
git commit -m "fix: show actual dates instead of relative time on ideas"
```

---

### Task 16: Fix RobinhoodPositionCard Sizing

**Files:**
- Modify: `frontend/src/components/stock/RobinhoodPositionCard.tsx`

**Step 1: Add consistent sizing and tabular-nums**

In the position card, ensure all grid cells have consistent heights and font sizing:

- Add `tabular-nums` to all numeric displays
- Set explicit `min-h` on the grid cells for uniformity
- Ensure the diversity ring and cost display align properly

Key changes:
- Shares/Market value row: `min-h-[4rem]` on grid cells
- Avg cost/Diversity row: same `min-h-[4rem]`
- All monetary values: `font-mono tabular-nums`
- Returns section: consistent padding

**Step 2: Make "More Stats" more visible**

In `StockHubContent.tsx`, change the More Stats button label and styling:

Replace line 151:
```tsx
<span>More Stats</span>
```
With:
```tsx
<span>Stats & Fundamentals</span>
```

On desktop, default to open. Update the initial state (line 66):
```typescript
const [moreStatsOpen, setMoreStatsOpen] = useState(false);
```

And in useEffect (line 86-87), default to true on desktop:
```typescript
const statsOpen = localStorage.getItem(LS_MORE_STATS);
if (statsOpen === null) {
  // Default open on desktop
  setMoreStatsOpen(window.innerWidth >= 1024);
} else {
  setMoreStatsOpen(statsOpen === 'true');
}
```

**Step 3: Build and verify**

```bash
npm run build
```

**Step 4: Commit**

```bash
git add frontend/src/components/stock/RobinhoodPositionCard.tsx frontend/src/components/stock/StockHubContent.tsx
git commit -m "fix: uniform position card sizing, more visible Stats & Fundamentals toggle"
```

---

### Task 17: QQQ Splash Polish

**Files:**
- Modify: `frontend/src/components/ui/QQQSplash.tsx`

**Step 1: Tighten letter spacing and simplify animation**

In the QQQ letters container, add tighter tracking:
```tsx
<div className="flex items-baseline tracking-tighter gap-0">
```

Remove the glow pulse animation step (lines 75-83 in the animation sequence). Simplify to:
1. Letters fade-in + scale from 0.8→1.0 (no stagger, or very subtle 50ms)
2. Subtitle slides up
3. Brief hold
4. Fade out

**Step 2: Use a cleaner font**

Replace `Playfair Display` with `DM Serif Display` or keep the system serif stack but with heavier weight. The key issue from the screenshots is the letters look disconnected and the serif styling is too ornate.

**Step 3: Build and verify**

```bash
npm run build
```

**Step 4: Commit**

```bash
git add frontend/src/components/ui/QQQSplash.tsx
git commit -m "polish: cleaner QQQ splash animation and font"
```

---

### Task 18: Sign-In Page Fix

**Files:**
- Modify: `frontend/src/components/ui/SigninIntro.tsx:191-200`

**Step 1: Fix the "or continue with" divider**

Find the divider section (around line 191-200). It likely has a background color or border that creates the grey box. Change to:

```tsx
<div className="relative flex items-center my-4">
  <div className="flex-1 border-t border-white/20" />
  <span className="px-3 text-xs text-white/50 bg-transparent">or continue with</span>
  <div className="flex-1 border-t border-white/20" />
</div>
```

The key fix is `bg-transparent` instead of any background color, and using `border-white/20` for subtle lines.

**Step 2: Increase QQQ text contrast**

In the logo/title section, increase the font weight or add a subtle text-shadow for better readability against the liquid gradient:

```tsx
<span className="text-4xl font-bold text-white drop-shadow-lg" style={{ textShadow: '0 2px 8px rgba(0,0,0,0.5)' }}>
  QQQ
</span>
```

**Step 3: Build and verify**

```bash
npm run build
```

**Step 4: Commit**

```bash
git add frontend/src/components/ui/SigninIntro.tsx
git commit -m "fix: remove grey box from sign-in divider, improve QQQ contrast"
```

---

### Task 19: Fix PortfolioSummary Number Overflow

**Files:**
- Modify: `frontend/src/components/dashboard/PortfolioSummary.tsx`

**Step 1: Add tabular-nums and overflow handling**

Find the metric card values and ensure they have:
- `tabular-nums` for aligned numbers
- `truncate` or `text-ellipsis overflow-hidden` for cards that overflow on mobile
- `min-w-0` on flex children to allow shrinking

**Step 2: Fix the CardSpotlight glow**

If the white glow issue is from CardSpotlight's radial gradient, add a check to reduce the spotlight intensity on table/grid components. This may be in `frontend/src/components/ui/CardSpotlight.tsx`.

**Step 3: Build and verify**

```bash
npm run build
```

**Step 4: Commit**

```bash
git add frontend/src/components/dashboard/PortfolioSummary.tsx
git commit -m "fix: number overflow on portfolio summary cards, reduce spotlight glow"
```

---

### Task 20: Final Build Verification and Deploy

**Step 1: Full production build**

```bash
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend
npm run build
```

Expected: Clean build with zero errors.

**Step 2: Backend lint check**

```bash
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project
ruff check app/routes/stocks.py app/routes/portfolio.py
```

Expected: No lint errors.

**Step 3: Run backend tests**

```bash
pytest tests/ -v -m "not openai and not integration" --tb=short
```

Expected: All tests pass.

**Step 4: Commit any remaining changes**

```bash
git status  # Check both repos
```

**Step 5: Deploy backend to EC2 (if ready)**

```bash
# On EC2:
cd /home/ubuntu/llm-portfolio
git pull origin hoodui
pip install -r requirements.txt
sudo systemctl restart api.service
```

**Step 6: Push frontend for Vercel deploy**

```bash
cd c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend
git push origin main
```

---

## Summary

| Task | Phase | Description | Files Changed |
|------|-------|-------------|---------------|
| 1 | Data | Backfill SnapTrade activities | Run script (no code) |
| 2 | Data | Re-ingest Discord + re-parse ideas | Run scripts (no code) |
| 3 | API | Per-stock activities endpoint | `stocks.py` |
| 4 | API | Multi-symbol idea query fix | `stocks.py` |
| 5 | API | Add weekChangePct to positions | `portfolio.py` |
| 6 | Frontend | TypeScript types update | `api.ts` |
| 7 | Frontend | BFF route for stock activities | New route file |
| 8 | Frontend | useStockActivities hook | New hook file |
| 9 | Frontend | TradeRecap component | New + `page.tsx` |
| 10 | Frontend | DailyMoversTable component | New + `page.tsx` |
| 11 | Frontend | HoldingsTable avg cost + glow fix | `HoldingsTable.tsx` |
| 12 | Frontend | TopMovers sparklines | `TopMovers.tsx` |
| 13 | Frontend | Dashboard layout restructure | `page.tsx` |
| 14 | Frontend | Trades tab in stock detail | New + `StockHubContent.tsx` |
| 15 | Frontend | Fix idea dates | `IdeasPanel.tsx` |
| 16 | Frontend | Position card sizing + More Stats | `RobinhoodPositionCard.tsx` + `StockHubContent.tsx` |
| 17 | Frontend | QQQ splash polish | `QQQSplash.tsx` |
| 18 | Frontend | Sign-in divider fix | `SigninIntro.tsx` |
| 19 | Frontend | Number overflow fix | `PortfolioSummary.tsx` |
| 20 | Both | Final build + deploy | Verification only |
