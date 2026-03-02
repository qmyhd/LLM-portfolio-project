# Stock Detail Page UX Refinement — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix layout, data display, and context UX issues on the stock detail page and positions tables.

**Architecture:** Incremental refinement of existing components. Add `react-resizable-panels` for the chart/tab split. Add inline context expansion to IdeasPanel and RawMessagesPanel. Fix quantity formatting across 6 components. Rebuild position card for per-account breakdown.

**Tech Stack:** Next.js 14, React 18, TypeScript, react-resizable-panels, Tailwind CSS, SWR

**Frontend root:** `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend\`

---

### Task 1: Add `formatQuantity` helper to format.ts

**Files:**
- Modify: `src/lib/format.ts` (append after line 163)

**Step 1: Add `formatQuantity` function**

Add to the end of `src/lib/format.ts`:

```typescript
/**
 * Format a share quantity — strips floating-point noise.
 * Whole numbers → 0 decimals, fractional → up to 4 decimals (trailing zeros stripped).
 * `formatQuantity(10)`              → `"10"`
 * `formatQuantity(1.7226000000001)` → `"1.7226"`
 * `formatQuantity(0.5)`             → `"0.5"`
 * `formatQuantity(null)`            → `"—"`
 */
export function formatQuantity(
  n: number | null | undefined,
  opts?: { placeholder?: string },
): string {
  const placeholder = opts?.placeholder ?? '—';
  if (n == null || Number.isNaN(n)) return placeholder;
  const v = safe(n);
  if (Number.isInteger(v)) return v.toLocaleString();
  // Round to 4 decimals to strip IEEE 754 noise, then remove trailing zeros
  return parseFloat(v.toFixed(4)).toString();
}
```

**Step 2: Verify build**

Run: `cd frontend && npx next build 2>&1 | head -5`
Expected: No errors from format.ts

**Step 3: Commit**

```bash
git add src/lib/format.ts
git commit -m "feat: add formatQuantity helper to strip floating-point noise"
```

---

### Task 2: Fix quantity display in all 6 components

**Files:**
- Modify: `src/app/positions/page.tsx:360` — change `{pos.quantity}` → `{formatQuantity(pos.quantity)}`
- Modify: `src/components/dashboard/HoldingsTable.tsx:345` — change `{position.quantity}` → `{formatQuantity(position.quantity)}`
- Modify: `src/components/dashboard/CryptoSection.tsx:119` — change `{position.quantity}` → `{formatQuantity(position.quantity)}`
- Modify: `src/components/dashboard/PositionsTable.tsx:217` — change `{position.quantity}` → `{formatQuantity(position.quantity)}`
- Modify: `src/components/stock/PositionCard.tsx:73` — change `{position.quantity} shares` → `{formatQuantity(position.quantity)} shares`

Each file needs `formatQuantity` added to its import from `@/lib/format`.

**Step 1: Fix positions/page.tsx**

At the import line (should already import `formatMoney` from `@/lib/format`), add `formatQuantity`.

Change line 360 from:
```tsx
{pos.quantity}
```
to:
```tsx
{formatQuantity(pos.quantity)}
```

**Step 2: Fix HoldingsTable.tsx**

Add `formatQuantity` to the format import. Change line 345 from:
```tsx
{position.quantity}
```
to:
```tsx
{formatQuantity(position.quantity)}
```

**Step 3: Fix CryptoSection.tsx**

Add `formatQuantity` to the format import. Change line 119 from:
```tsx
{position.quantity}
```
to:
```tsx
{formatQuantity(position.quantity)}
```

**Step 4: Fix PositionsTable.tsx**

Add `formatQuantity` to the format import. Change line 217 from:
```tsx
{position.quantity}
```
to:
```tsx
{formatQuantity(position.quantity)}
```

**Step 5: Fix PositionCard.tsx**

Add `formatQuantity` to the format import. Change line 73 from:
```tsx
{position.quantity} shares
```
to:
```tsx
{formatQuantity(position.quantity)} shares
```

**Step 6: Verify build**

Run: `cd frontend && npx next build 2>&1 | tail -20`
Expected: Build succeeds, no type errors

**Step 7: Commit**

```bash
git add src/app/positions/page.tsx src/components/dashboard/HoldingsTable.tsx src/components/dashboard/CryptoSection.tsx src/components/dashboard/PositionsTable.tsx src/components/stock/PositionCard.tsx
git commit -m "fix: use formatQuantity to strip floating-point noise in all quantity displays"
```

---

### Task 3: Install react-resizable-panels

**Files:**
- Modify: `package.json`

**Step 1: Install the package**

Run: `cd frontend && npm install react-resizable-panels`

**Step 2: Verify it installed**

Run: `grep react-resizable-panels package.json`
Expected: Line showing `"react-resizable-panels": "^X.X.X"`

**Step 3: Commit**

```bash
git add package.json package-lock.json
git commit -m "chore: add react-resizable-panels for stock detail layout"
```

---

### Task 4: Restructure StockHubContent with resizable panels

This is the largest task. We're changing the bottom section of `StockHubContent.tsx` to use `react-resizable-panels` and moving trades out of the tab system.

**Files:**
- Modify: `src/components/stock/StockHubContent.tsx`

**Step 1: Update imports**

Add to the top of StockHubContent.tsx (after existing imports):

```typescript
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';
```

**Step 2: Update TabKey type and TABS array**

Change lines 26-35 from:

```typescript
type TabKey = 'chat' | 'ideas' | 'trades' | 'raw' | 'insights' | 'notes';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'chat', label: 'Chat' },
  { key: 'ideas', label: 'Ideas' },
  { key: 'trades', label: 'Trades' },
  { key: 'raw', label: 'Raw' },
  { key: 'insights', label: 'Insights' },
  { key: 'notes', label: 'Notes' },
];
```

to:

```typescript
type TabKey = 'chat' | 'ideas' | 'raw' | 'insights' | 'notes';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'chat', label: 'Chat' },
  { key: 'ideas', label: 'Ideas' },
  { key: 'raw', label: 'Raw' },
  { key: 'insights', label: 'Insights' },
  { key: 'notes', label: 'Notes' },
];
```

**Step 3: Replace the bottom section layout (lines 177-272)**

Replace the entire `{/* ── Bottom section: Chart + Tabs ── */}` block (from the opening `<div className="flex flex-col lg:flex-row` through the closing `</aside>` and `</div>`) with:

```tsx
      {/* ── Bottom section: Chart + Trades | Tabs (resizable) ── */}
      <div className="flex-1 min-h-0 lg:h-[calc(100vh-320px)]">
        {/* Mobile: stacked layout */}
        <div className="flex flex-col lg:hidden">
          {/* Chart */}
          <div className="border-b border-border">
            <div className="flex items-center justify-end gap-1 px-3 py-1.5 border-b border-border bg-background-secondary/50">
              <button
                onClick={toggleChartProvider}
                className={clsx(
                  'p-1.5 rounded-md transition-colors',
                  chartProvider === 'tradingview'
                    ? 'bg-primary/20 text-primary'
                    : 'text-foreground-muted hover:text-foreground hover:bg-background-tertiary',
                )}
                title={`Switch to ${chartProvider === 'lightweight' ? 'TradingView' : 'Lightweight'} chart`}
              >
                <ChartBarIcon className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={handleRefresh}
                className="p-1.5 rounded-md hover:bg-background-tertiary text-foreground-muted hover:text-foreground transition-colors"
                title="Refresh data"
              >
                <ArrowPathIcon className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="min-h-[300px]">
              <Suspense fallback={<ChartSkeleton />}>
                {chartProvider === 'tradingview' ? (
                  <TradingViewChart symbol={ticker} key={`tv-chart-${refreshKey}`} theme="dark" height={300} autosize={true} />
                ) : (
                  <StockChart ticker={ticker} key={`chart-${refreshKey}`} />
                )}
              </Suspense>
            </div>
          </div>

          {/* Trades (mobile) */}
          <div className="border-b border-border max-h-[250px] overflow-y-auto">
            <div className="px-3 py-2 border-b border-border bg-background-secondary/50">
              <span className="text-xs font-medium text-foreground-muted">Recent Trades</span>
            </div>
            <TradesPanel ticker={ticker} key={`trades-mobile-${refreshKey}`} />
          </div>

          {/* Tabs (mobile) */}
          <div className="min-h-[300px] flex flex-col bg-background-secondary/80">
            <div className="flex border-b border-border bg-background-secondary overflow-x-auto">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={clsx(
                    'flex-1 px-3 py-2.5 text-sm font-medium transition-colors whitespace-nowrap',
                    activeTab === tab.key
                      ? 'text-primary border-b-2 border-primary bg-primary/5'
                      : 'text-foreground-muted hover:text-foreground hover:bg-background-tertiary',
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <div className="flex-1 overflow-hidden">
              <Suspense
                fallback={
                  <div className="p-4 space-y-3">
                    {[...Array(5)].map((_, i) => (
                      <div key={i} className="skeleton h-16 rounded-lg" />
                    ))}
                  </div>
                }
              >
                {activeTab === 'chat' && <ChatWidget ticker={ticker} key={`chat-${refreshKey}`} />}
                {activeTab === 'ideas' && <IdeasPanel ticker={ticker} key={`ideas-${refreshKey}`} />}
                {activeTab === 'raw' && <RawMessagesPanel ticker={ticker} key={`raw-${refreshKey}`} />}
                {activeTab === 'insights' && <OpenBBInsightsPanel ticker={ticker} key={`insights-${refreshKey}`} />}
                {activeTab === 'notes' && <NotesPanel ticker={ticker} key={`notes-${refreshKey}`} />}
              </Suspense>
            </div>
          </div>
        </div>

        {/* Desktop: resizable panels */}
        <PanelGroup direction="horizontal" autoSaveId="stock-panel-sizes" className="hidden lg:flex h-full">
          {/* Left panel: Chart + Trades */}
          <Panel defaultSize={60} minSize={30}>
            <div className="flex flex-col h-full">
              {/* Chart controls */}
              <div className="flex items-center justify-end gap-1 px-3 py-1.5 border-b border-border bg-background-secondary/50">
                <button
                  onClick={toggleChartProvider}
                  className={clsx(
                    'p-1.5 rounded-md transition-colors',
                    chartProvider === 'tradingview'
                      ? 'bg-primary/20 text-primary'
                      : 'text-foreground-muted hover:text-foreground hover:bg-background-tertiary',
                  )}
                  title={`Switch to ${chartProvider === 'lightweight' ? 'TradingView' : 'Lightweight'} chart`}
                >
                  <ChartBarIcon className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={handleRefresh}
                  className="p-1.5 rounded-md hover:bg-background-tertiary text-foreground-muted hover:text-foreground transition-colors"
                  title="Refresh data"
                >
                  <ArrowPathIcon className="h-3.5 w-3.5" />
                </button>
              </div>

              {/* Chart */}
              <div className="flex-1 min-h-[300px]">
                <Suspense fallback={<ChartSkeleton />}>
                  {chartProvider === 'tradingview' ? (
                    <TradingViewChart symbol={ticker} key={`tv-chart-${refreshKey}`} theme="dark" height={400} autosize={true} />
                  ) : (
                    <StockChart ticker={ticker} key={`chart-${refreshKey}`} />
                  )}
                </Suspense>
              </div>

              {/* Trades pinned below chart */}
              <div className="border-t border-border max-h-[250px] overflow-y-auto flex-shrink-0">
                <div className="px-3 py-2 border-b border-border bg-background-secondary/50 sticky top-0 z-10">
                  <span className="text-xs font-medium text-foreground-muted">Recent Trades</span>
                </div>
                <TradesPanel ticker={ticker} key={`trades-${refreshKey}`} />
              </div>
            </div>
          </Panel>

          {/* Resize handle */}
          <PanelResizeHandle className="w-1.5 bg-border hover:bg-primary/50 transition-colors cursor-col-resize" />

          {/* Right panel: Tabs */}
          <Panel defaultSize={40} minSize={25}>
            <aside className="h-full flex flex-col bg-background-secondary/80 backdrop-blur-md">
              {/* Tab switcher */}
              <div className="flex border-b border-border bg-background-secondary overflow-x-auto">
                {TABS.map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => setActiveTab(tab.key)}
                    className={clsx(
                      'flex-1 px-3 py-2.5 text-sm font-medium transition-colors whitespace-nowrap',
                      activeTab === tab.key
                        ? 'text-primary border-b-2 border-primary bg-primary/5'
                        : 'text-foreground-muted hover:text-foreground hover:bg-background-tertiary',
                    )}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div className="flex-1 overflow-hidden">
                <Suspense
                  fallback={
                    <div className="p-4 space-y-3">
                      {[...Array(5)].map((_, i) => (
                        <div key={i} className="skeleton h-16 rounded-lg" />
                      ))}
                    </div>
                  }
                >
                  {activeTab === 'chat' && <ChatWidget ticker={ticker} key={`chat-${refreshKey}`} />}
                  {activeTab === 'ideas' && <IdeasPanel ticker={ticker} key={`ideas-${refreshKey}`} />}
                  {activeTab === 'raw' && <RawMessagesPanel ticker={ticker} key={`raw-${refreshKey}`} />}
                  {activeTab === 'insights' && <OpenBBInsightsPanel ticker={ticker} key={`insights-${refreshKey}`} />}
                  {activeTab === 'notes' && <NotesPanel ticker={ticker} key={`notes-${refreshKey}`} />}
                </Suspense>
              </div>
            </aside>
          </Panel>
        </PanelGroup>
      </div>
```

**Step 4: Remove the old trades tab conditional render**

The old `{activeTab === 'trades' && <TradesPanel ... />}` is gone since we replaced the entire block. Verify there are no remaining references to `activeTab === 'trades'` in the file.

**Step 5: Verify build**

Run: `cd frontend && npx next build 2>&1 | tail -20`
Expected: Build succeeds

**Step 6: Commit**

```bash
git add src/components/stock/StockHubContent.tsx
git commit -m "feat: resizable panels for stock detail, trades pinned below chart"
```

---

### Task 5: Add IdeaContext type and inline context accordion to IdeasPanel

**Files:**
- Modify: `src/types/api.ts` (add context types)
- Modify: `src/components/stock/IdeasPanel.tsx` (add context accordion)

**Step 1: Add context types to api.ts**

Append after the `IdeasResponse` interface (after line 239):

```typescript
// =============================================================================
// Idea Context (surrounding Discord messages)
// =============================================================================

export interface ContextMessage {
  messageId: string;
  content: string;
  author: string;
  sentAt: string;
  channel: string;
  isParent: boolean;
}

export interface IdeaContextResponse {
  idea: StockIdea;
  parentMessage: ContextMessage | null;
  contextMessages: ContextMessage[];
}
```

**Step 2: Add context accordion to IdeaCard in IdeasPanel.tsx**

Add a `useState` for expanded idea ID and a fetch-on-expand pattern.

At the top of IdeasPanel.tsx, add to imports:

```typescript
import type { ContextMessage } from '@/types/api';
import { ChevronUpIcon } from '@heroicons/react/24/outline';
import { formatRelativeTime } from '@/lib/format';
```

Modify the `IdeaCard` component. Replace the entire function (lines 256-334) with:

```tsx
function IdeaCard({ idea, onAuthorClick }: IdeaCardProps) {
  const [showContext, setShowContext] = useState(false);
  const [contextMessages, setContextMessages] = useState<ContextMessage[]>([]);
  const [contextLoading, setContextLoading] = useState(false);

  const DirectionIcon =
    idea.direction === 'bullish'
      ? ArrowTrendingUpIcon
      : idea.direction === 'bearish'
      ? ArrowTrendingDownIcon
      : MinusIcon;

  const directionColor = directionTextColor(idea.direction);

  const toggleContext = async () => {
    if (showContext) {
      setShowContext(false);
      return;
    }
    if (contextMessages.length > 0) {
      setShowContext(true);
      return;
    }
    setContextLoading(true);
    try {
      const res = await fetch(`/api/ideas/${idea.id}/context`);
      if (res.ok) {
        const data = await res.json();
        setContextMessages(data.contextMessages || []);
      }
    } catch {
      // Silently fail — context is supplementary
    } finally {
      setContextLoading(false);
      setShowContext(true);
    }
  };

  return (
    <div className="p-4 hover:bg-background-tertiary/50 transition-colors">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <DirectionIcon className={clsx('w-4 h-4', directionColor)} />
          <span className={clsx('text-sm font-medium capitalize', directionColor)}>
            {idea.direction}
          </span>
          <span className="text-xs text-foreground-muted">{formatNumber((idea.confidence ?? 0) * 100, 0)}%</span>
        </div>
        <span className="text-xs text-foreground-subtle">{formatDate(idea.sourceCreatedAt, 'short')}</span>
      </div>

      {/* Labels */}
      <div className="flex flex-wrap gap-1 mb-2">
        {idea.labels.map((label) => (
          <span
            key={label}
            className={clsx(
              'px-1.5 py-0.5 text-2xs font-medium rounded',
              LABEL_COLORS[label] || 'bg-background-tertiary text-foreground-muted'
            )}
          >
            {label.replace('_', ' ')}
          </span>
        ))}
      </div>

      {/* Text */}
      <p className="text-sm text-foreground leading-relaxed">{idea.ideaText}</p>

      {/* Price levels */}
      {(() => {
        const entry = getLevelValue(idea, 'entry');
        const target = getLevelValue(idea, 'target');
        const stop = getLevelValue(idea, 'stop');
        if (!entry && !target && !stop) return null;
        return (
          <div className="flex flex-wrap gap-3 mt-2 text-xs font-mono">
            {entry && (
              <span className="text-foreground-muted">
                Entry: <span className="text-foreground">${formatNumber(entry)}</span>
              </span>
            )}
            {target && (
              <span className="text-foreground-muted">
                Target: <span className="text-profit">${formatNumber(target)}</span>
              </span>
            )}
            {stop && (
              <span className="text-foreground-muted">
                Stop: <span className="text-loss">${formatNumber(stop)}</span>
              </span>
            )}
          </div>
        );
      })()}

      {/* Author + Context toggle row */}
      <div className="flex items-center justify-between mt-2">
        <button
          onClick={() => onAuthorClick(idea.author)}
          className="text-xs text-foreground-muted hover:text-primary transition-colors"
        >
          @{idea.author}
        </button>
        <button
          onClick={toggleContext}
          className="flex items-center gap-1 text-xs text-foreground-muted hover:text-primary transition-colors"
        >
          {contextLoading ? (
            <span className="animate-pulse">Loading...</span>
          ) : (
            <>
              {showContext ? (
                <ChevronUpIcon className="h-3 w-3" />
              ) : (
                <ChevronDownIcon className="h-3 w-3" />
              )}
              {showContext ? 'Hide context' : 'Show context'}
            </>
          )}
        </button>
      </div>

      {/* Context accordion */}
      {showContext && contextMessages.length > 0 && (
        <div className="mt-3 border border-border rounded-lg overflow-hidden">
          {contextMessages.map((msg) => (
            <div
              key={msg.messageId}
              className={clsx(
                'px-3 py-2 text-xs border-b border-border last:border-b-0',
                msg.isParent
                  ? 'bg-primary/5 border-l-2 border-l-primary'
                  : 'bg-background-secondary/50',
              )}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-medium text-foreground">
                  {msg.isParent && '▶ '}@{msg.author}
                </span>
                <span className="text-foreground-subtle">
                  {formatRelativeTime(msg.sentAt)}
                </span>
              </div>
              <p className="text-foreground/80 whitespace-pre-wrap break-words">{msg.content}</p>
            </div>
          ))}
        </div>
      )}

      {showContext && contextMessages.length === 0 && !contextLoading && (
        <p className="mt-3 text-xs text-foreground-muted italic">No context messages available</p>
      )}
    </div>
  );
}
```

**Step 3: Verify build**

Run: `cd frontend && npx next build 2>&1 | tail -20`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add src/types/api.ts src/components/stock/IdeasPanel.tsx
git commit -m "feat: inline context accordion for ideas showing surrounding Discord messages"
```

---

### Task 6: Add inline context expansion to RawMessagesPanel

**Files:**
- Modify: `src/components/stock/RawMessagesPanel.tsx`

**Step 1: Add context expansion to raw messages**

Raw messages have a `messageId` field. We need a lightweight way to fetch surrounding messages. The backend `/ideas/{id}/context` endpoint takes an **idea ID** (from `user_ideas` table), not a raw message ID. For raw messages, we'll use the existing `/api/sentiment/messages` endpoint with offset to simulate context, OR we can add context fetching using the idea's `messageId` by searching for a matching idea.

Simpler approach: Since raw messages already come from `discord_parsed_ideas` (they share `messageId`), we can call `/api/ideas/{id}/context` if we know the idea ID. The RawMessage interface has an `id` field which IS the `discord_parsed_ideas.id`.

Replace the message card rendering (the `<div key={msg.id}>` block inside the map, lines 114-145) with a new component that supports expanding:

At the top of the file, add:

```typescript
import { ChevronDownIcon, ChevronUpIcon } from '@heroicons/react/24/outline';
import type { ContextMessage } from '@/types/api';
```

After the `RawMessagesPanel` function, add a new `RawMessageCard` component:

```tsx
function RawMessageCard({ msg, formatTime }: { msg: RawMessage; formatTime: (t: string | null) => string }) {
  const [showContext, setShowContext] = useState(false);
  const [contextMessages, setContextMessages] = useState<ContextMessage[]>([]);
  const [contextLoading, setContextLoading] = useState(false);

  const toggleContext = async () => {
    if (showContext) { setShowContext(false); return; }
    if (contextMessages.length > 0) { setShowContext(true); return; }
    setContextLoading(true);
    try {
      const res = await fetch(`/api/ideas/${msg.id}/context`);
      if (res.ok) {
        const data = await res.json();
        setContextMessages(data.contextMessages || []);
      }
    } catch { /* context is supplementary */ }
    finally { setContextLoading(false); setShowContext(true); }
  };

  return (
    <div className="p-3 rounded-lg bg-background-tertiary hover:bg-background-tertiary/80 transition-colors">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground">{msg.author}</span>
          <span className="text-xs text-foreground-muted">#{msg.channel}</span>
        </div>
        <span className="text-xs text-foreground-subtle">{formatTime(msg.createdAt)}</span>
      </div>

      {/* Content */}
      <p className="text-sm text-foreground/90 whitespace-pre-wrap break-words">{msg.ideaText}</p>

      {/* Direction badge + context toggle */}
      <div className="flex items-center justify-between mt-2">
        {msg.direction ? (
          <span className={`text-xs px-1.5 py-0.5 rounded ${
            msg.direction === 'bullish' ? 'bg-profit/20 text-profit' :
            msg.direction === 'bearish' ? 'bg-loss/20 text-loss' :
            'bg-foreground-muted/20 text-foreground-muted'
          }`}>
            {msg.direction}
          </span>
        ) : <span />}
        <button
          onClick={toggleContext}
          className="flex items-center gap-1 text-xs text-foreground-muted hover:text-primary transition-colors"
        >
          {contextLoading ? (
            <span className="animate-pulse">Loading...</span>
          ) : (
            <>
              {showContext ? <ChevronUpIcon className="h-3 w-3" /> : <ChevronDownIcon className="h-3 w-3" />}
              {showContext ? 'Hide context' : 'Show context'}
            </>
          )}
        </button>
      </div>

      {/* Context accordion */}
      {showContext && contextMessages.length > 0 && (
        <div className="mt-2 border border-border rounded-lg overflow-hidden">
          {contextMessages.map((cm) => (
            <div
              key={cm.messageId}
              className={`px-3 py-2 text-xs border-b border-border last:border-b-0 ${
                cm.isParent ? 'bg-primary/5 border-l-2 border-l-primary' : 'bg-background-secondary/50'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-medium text-foreground">{cm.isParent && '▶ '}@{cm.author}</span>
                <span className="text-foreground-subtle">{formatTime(cm.sentAt)}</span>
              </div>
              <p className="text-foreground/80 whitespace-pre-wrap break-words">{cm.content}</p>
            </div>
          ))}
        </div>
      )}
      {showContext && contextMessages.length === 0 && !contextLoading && (
        <p className="mt-2 text-xs text-foreground-muted italic">No context available</p>
      )}
    </div>
  );
}
```

Then in the `RawMessagesPanel` return, replace line 114:
```tsx
{messages.map((msg) => (
  <div key={msg.id} className="p-3 rounded-lg bg-background-tertiary hover:bg-background-tertiary/80 transition-colors">
    ...
  </div>
))}
```
with:
```tsx
{messages.map((msg) => (
  <RawMessageCard key={msg.id} msg={msg} formatTime={formatTime} />
))}
```

And remove the old inline card JSX (lines 115-145).

**Step 2: Verify build**

Run: `cd frontend && npx next build 2>&1 | tail -20`

**Step 3: Commit**

```bash
git add src/components/stock/RawMessagesPanel.tsx
git commit -m "feat: inline context accordion for raw messages panel"
```

---

### Task 7: Rebuild RobinhoodPositionCard with per-account breakdown

**Files:**
- Modify: `src/components/stock/RobinhoodPositionCard.tsx`

**Step 1: Rewrite the component**

Replace the entire content of `RobinhoodPositionCard.tsx` with:

```tsx
'use client';

import { useState, useEffect } from 'react';
import { BanknotesIcon } from '@heroicons/react/24/outline';
import type { Position } from '@/types/api';
import { formatMoney, formatSignedMoney, formatPercent, formatQuantity } from '@/lib/format';
import { pnlTextColor } from '@/lib/colors';
import { PortfolioDiversityRing } from './PortfolioDiversityRing';

interface RobinhoodPositionCardProps {
  ticker: string;
}

interface AggregatedPosition {
  totalShares: number;
  totalValue: number;
  totalCost: number;
  weightedAvgCost: number;
  dayChange: number;
  dayChangePct: number | null;
  unrealizedPL: number;
  unrealizedPLPct: number;
  diversity: number | null;
  accounts: { name: string; shares: number; value: number }[];
}

function aggregatePositions(positions: Position[], totalEquity: number): AggregatedPosition {
  const totalShares = positions.reduce((s, p) => s + p.quantity, 0);
  const totalValue = positions.reduce((s, p) => s + p.equity, 0);
  const totalCost = positions.reduce((s, p) => s + p.quantity * p.averageBuyPrice, 0);
  const weightedAvgCost = totalShares > 0 ? totalCost / totalShares : 0;
  const dayChange = positions.reduce((s, p) => s + (p.dayChange ?? 0), 0);
  const unrealizedPL = totalValue - totalCost;
  const unrealizedPLPct = totalCost > 0 ? (unrealizedPL / totalCost) * 100 : 0;

  // Day change pct: weighted by equity
  let dayChangePct: number | null = null;
  const positionsWithDay = positions.filter((p) => p.dayChangePercent != null);
  if (positionsWithDay.length > 0) {
    const weightedSum = positionsWithDay.reduce((s, p) => s + (p.dayChangePercent ?? 0) * p.equity, 0);
    const totalEq = positionsWithDay.reduce((s, p) => s + p.equity, 0);
    dayChangePct = totalEq > 0 ? weightedSum / totalEq : null;
  }

  const diversity = totalEquity > 0 ? (totalValue / totalEquity) * 100 : null;

  const accounts = positions.map((p) => ({
    name: p.accountId, // Will show account ID; could be mapped to friendly names
    shares: p.quantity,
    value: p.equity,
  }));

  return { totalShares, totalValue, totalCost, weightedAvgCost, dayChange, dayChangePct, unrealizedPL, unrealizedPLPct, diversity, accounts };
}

export function RobinhoodPositionCard({ ticker }: RobinhoodPositionCardProps) {
  const [agg, setAgg] = useState<AggregatedPosition | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch('/api/portfolio');
        if (!res.ok) { setAgg(null); return; }
        const data = await res.json();
        const positions: Position[] = (data.positions || []).filter(
          (p: Position) => p.symbol === ticker,
        );
        if (positions.length === 0) { setAgg(null); return; }
        const totalEquity = data.summary?.totalEquity ?? 0;
        setAgg(aggregatePositions(positions, totalEquity));
      } catch {
        setAgg(null);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [ticker]);

  if (loading) {
    return (
      <div className="card p-4 animate-pulse">
        <div className="skeleton h-4 w-24 mb-3 rounded" />
        <div className="skeleton h-6 w-32 mb-2 rounded" />
        <div className="skeleton h-3 w-full rounded" />
      </div>
    );
  }

  if (!agg) {
    return (
      <div className="card p-4">
        <div className="flex items-center gap-2 text-foreground-muted mb-2">
          <BanknotesIcon className="h-4 w-4" />
          <span className="text-sm font-medium">Your Position</span>
        </div>
        <p className="text-sm text-foreground-muted">No position in {ticker}</p>
      </div>
    );
  }

  return (
    <div className="card p-4">
      {/* Header */}
      <div className="flex items-center gap-2 text-foreground-muted mb-4">
        <BanknotesIcon className="h-4 w-4" />
        <span className="text-sm font-medium">Your position</span>
      </div>

      {/* Shares + Market value row */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div className="min-h-[3.5rem]">
          <p className="text-xs text-foreground-muted mb-1">Shares</p>
          <p className="text-lg font-bold font-mono tabular-nums">{formatQuantity(agg.totalShares)}</p>
        </div>
        <div className="min-h-[3.5rem]">
          <p className="text-xs text-foreground-muted mb-1">Market value</p>
          <p className="text-lg font-bold font-mono tabular-nums">{formatMoney(agg.totalValue)}</p>
        </div>
      </div>

      {/* Average cost + Diversity ring row */}
      <div className="flex items-center justify-between mb-4">
        <div className="min-h-[3.5rem]">
          <p className="text-xs text-foreground-muted mb-1">Average cost</p>
          <p className="text-base font-mono font-semibold tabular-nums">{formatMoney(agg.weightedAvgCost)}</p>
        </div>
        {agg.diversity != null && (
          <div className="text-center">
            <p className="text-xs text-foreground-muted mb-1">Diversity</p>
            <PortfolioDiversityRing percentage={agg.diversity} size={56} />
          </div>
        )}
      </div>

      {/* Today's return */}
      <div className="py-3 border-t border-border">
        <p className="text-xs text-foreground-muted mb-1">Today&apos;s return</p>
        <span className={`text-sm font-semibold font-mono tabular-nums ${pnlTextColor(agg.dayChange)}`}>
          {formatSignedMoney(agg.dayChange)}{' '}
          ({formatPercent(agg.dayChangePct, 2, { showSign: true })})
        </span>
      </div>

      {/* Total return */}
      <div className="py-3 border-t border-border">
        <p className="text-xs text-foreground-muted mb-1">Total return</p>
        <span className={`text-sm font-semibold font-mono tabular-nums ${pnlTextColor(agg.unrealizedPL)}`}>
          {formatSignedMoney(agg.unrealizedPL)}{' '}
          ({formatPercent(agg.unrealizedPLPct, 2, { showSign: true })})
        </span>
      </div>

      {/* Per-account breakdown (only if multiple accounts) */}
      {agg.accounts.length > 1 && (
        <div className="pt-3 border-t border-border">
          <p className="text-xs text-foreground-muted mb-2">Accounts</p>
          <div className="space-y-1.5">
            {agg.accounts.map((acct) => (
              <div key={acct.name} className="flex items-center justify-between text-xs">
                <span className="text-foreground-muted truncate max-w-[120px]" title={acct.name}>
                  {acct.name.slice(0, 8)}...
                </span>
                <div className="flex items-center gap-3 font-mono tabular-nums">
                  <span className="text-foreground-muted">{formatQuantity(acct.shares)} sh</span>
                  <span className="text-foreground">{formatMoney(acct.value)}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify build**

Run: `cd frontend && npx next build 2>&1 | tail -20`

**Step 3: Commit**

```bash
git add src/components/stock/RobinhoodPositionCard.tsx
git commit -m "feat: per-account position breakdown on stock detail page"
```

---

### Task 8: Fix responsive text overflow in positions tables

**Files:**
- Modify: `src/app/positions/page.tsx:356-357` — add truncate to company name
- Modify: `src/components/dashboard/HoldingsTable.tsx` — add truncate to company name column

**Step 1: Fix positions page company name**

At line 356-357 of `positions/page.tsx`, the company name cell:
```tsx
<td className="px-4 py-3 text-sm text-foreground-muted">
  {pos.companyName}
</td>
```
Change to:
```tsx
<td className="px-4 py-3 text-sm text-foreground-muted max-w-[200px] truncate" title={pos.companyName}>
  {pos.companyName}
</td>
```

**Step 2: Fix HoldingsTable company name**

Find the company name rendering in HoldingsTable.tsx (it's in the symbol cell as a secondary line). Add `truncate` and `max-w` to prevent overflow.

**Step 3: Verify build**

Run: `cd frontend && npx next build 2>&1 | tail -20`

**Step 4: Commit**

```bash
git add src/app/positions/page.tsx src/components/dashboard/HoldingsTable.tsx
git commit -m "fix: add text truncation to company name columns for responsive layout"
```

---

### Task 9: Verify the TopMovers hook fix (already applied)

**Files:**
- Verify: `src/components/dashboard/TopMovers.tsx`

**Step 1: Confirm the fix**

Read `TopMovers.tsx` and verify `useSparklines('1M')` is on line 33, before any early returns.

**Step 2: Commit if not already committed**

The fix was already applied earlier. If it's not committed yet:
```bash
git add src/components/dashboard/TopMovers.tsx
git commit -m "fix: move useSparklines above early returns to fix React error #310"
```

---

### Task 10: Final build verification and deploy

**Step 1: Full build check**

Run: `cd frontend && npx next build`
Expected: Clean build with no errors

**Step 2: Review git status**

Run: `git status` and `git log --oneline -10`
Expected: All changes committed in separate atomic commits

**Step 3: Push to main for Vercel auto-deploy**

Run: `git push origin main`

**Step 4: Monitor Vercel deployment**

Check Vercel dashboard or run: `vercel ls --prod` (if Vercel CLI is configured)
Expected: Successful deployment without "internal error"
