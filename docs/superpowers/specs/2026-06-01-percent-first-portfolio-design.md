# Percent-First Portfolio — Design Spec

- **Date:** 2026-06-01
- **Status:** Design — revised after adversarial review; pending user review
- **Project:** A of 2 (sibling project: AI-assisted stock profiling)

> **Frontend path note:** the Next.js app is nested at
> `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend\src\…`.
> All frontend paths below are written relative to that as `frontend/src/…`.

## Goal

Remove the big dollar account value and the cash / buying-power dependency from the
portfolio experience, and present performance as percentages. The driving constraint is to
**stop having to track cash and buying power** for the numbers to be meaningful.

## Locked decisions

1. **Scope — Moderate.** Account header drops the big $ total value, cash, and buying power.
   Per-position market value ($) and P/L ($) become **% weight + % return**. The equity curve
   becomes a **% return curve**. Factual prices and individual trade $ amounts stay. **Average
   cost per share stays visible and accurate** (the weighted-average basis — the same value the
   P/L % is derived from).
2. **Return method — current-holdings price performance.** Period returns = the weighted
   price return of the stocks you *currently* hold over the window, from price history.
   Flow-free: no cash / deposit / contribution tracking.
3. **Hero — selected-period return.** The big number tracks the active time tab; all-time
   total return and today's move appear as a context subline.
4. **Build strategy — frontend reframe + small, targeted backend additions.** Two backend
   changes only: a new return-series endpoint (with a new crypto price-series helper) and two
   already-computed percentage fields exposed on the risk report. `cash`/`buyingPower` stay in
   the API payload, unrendered. `portfolio.py` aggregation logic is otherwise untouched.
5. **Clarity (requirement).** The site explicitly labels the headline/curve as *current-holdings*
   performance, not actual account history.

## Backend

### New endpoint — `GET /portfolio/return-series?period=&bucket=`

- **Params:** `period ∈ {1W,1M,3M,YTD,1Y,ALL}`; `bucket` (use `validate_bucket` +
  `bucket_filter_sql` + `LEFT JOIN accounts` per `src/bucket.py`).
- **Algorithm — weighted normalized-return index (NOT a raw value index).** A naive
  `index[t] = Σ qtyᵢ·priceᵢ[t]` with forward-fill distorts the basket (a holding missing at t₀
  either spikes the curve or silently rescales the denominator). Use instead:
  - Current holdings (`quantity > 0`, bucket-filtered). Fixed weight `wᵢ = equityᵢ / Σ equity`.
  - Per-holding baseline `t₀ᵢ` = the holding's **first available price within the window**.
  - Per-holding relative `rᵢ[t] = priceᵢ[t] / priceᵢ[t₀ᵢ] − 1` (intermediate gaps forward-filled).
  - `return[t] = Σ_{i with data at t} wᵢ′ · rᵢ[t]`, where `wᵢ′` renormalizes `wᵢ` over the
    holdings that have data at `t` (Σ weights = 1 at each `t`). Holdings not yet started are
    excluded and weights renormalized — no artificial jump.
  - `periodReturnPct = return[last]`.
- **Flow-free property:** weights come from *current* holdings and quantities never change over
  the window, so a mid-window deposit or new buy cannot move the number (unit-tested).
- **Price sources:**
  - **Equities** → `ohlcv_daily` via `price_service`.
  - **Crypto** → **NEW** helper `get_crypto_price_series(symbol, start, end)` in
    `market_data_service` (yfinance `.history`, using the existing `CRYPTO_IDENTITY` / `_yf_symbol`
    mapping). This is **new work** — `market_data_service` currently exposes only realtime quotes
    and fixed-bucket scalar returns, and `ohlcv_daily`/`price_service` are equity-only (crypto is
    explicitly stripped). *Alternative to evaluate in the plan:* derive crypto `price[t]` from
    `position_snapshots` if it stores per-row quantity.
  - **Date grid:** union of equity trading days; crypto (7-days/week) forward-filled onto the
    equity calendar.
- **`ALL` window:** defined as `max(earliest common price date, today − 730d)` (matches the
  existing equity-curve `le=730` cap). Differing per-holding histories are handled by the
  per-holding `t₀ᵢ` baselines + weight renormalization above.
- **Response:** `{ period, asOf, periodReturnPct, points: [{ date, returnPct }] }`.
- **Edge cases:** empty portfolio → empty series + `0%`; single holding → its own normalized
  return; fully-sold positions are excluded (not current holdings).
- The existing `GET /portfolio/equity-curve` ($-based actual equity) remains but is unused by
  these views.

### Risk report — expose the already-computed VaR percentage

`risk.py` computes `var_95_1d_pct = percentile(returns, 5)` then multiplies by `total_value` and
**discards the percentage**. The risk payload (`PortfolioRiskReport` in `src/analysis/models.py`
and the frontend type) has **no equity/total field**, so VaR% **cannot** be derived client-side.

- **Add `var_95_1d_pct` and `var_95_5d_pct`** to `PortfolioRiskReport` (backend Pydantic +
  frontend type). They already exist in `risk.py:165` pre-multiply.
- `PortfolioRiskCard` renders the percentage directly. Because VaR is computed per bucket, the
  returned percentage is automatically the correct bucket-scoped value — no cross-fetch, no
  `VaR$/totalEquity` division (which was impossible and would have mismatched denominators).
- *(Note: the `total_value` fed into `risk.py` is itself unreliable today — see Project B's
  "bugs discovered": `SELECT SUM(total_value) FROM account_balances` references a non-existent
  column. Returning the percentage sidesteps that for the % display; the underlying $ VaR fix is
  handled with that bug.)*

### Reused, no change

`GET /portfolio` already returns `unrealizedPLPercent` (all-time vs cost), `dayChangePercent`
(today), per-position `openPnlPercent`, `dayChangePercent`, `weekChangePct`, `portfolioDiversity`
(% weight). `cashBalance`/`buyingPower` stay in the payload, unrendered.

## Frontend — component mapping (proposed; confirm in review)

- **`frontend/src/components/dashboard/RobinhoodHeader.tsx`** — remove big $ value, cash, buying
  power, $ change. Hero = `periodReturnPct` from `/portfolio/return-series` for the selected tab.
  Subline: `all-time +X% · today +Y%`. **Replace** the existing `getChangeForRange` derivation
  (which computes `change/start` off the $-equity curve, incl. flows) with the return-series value
  — not just a URL swap. Add the clarity caption + (i) tooltip. Keep tabs + positions count.
- **`frontend/src/components/portfolio/EquityCurveCard.tsx`** — repoint to `/portfolio/return-series`;
  **replace** `periodChange = (last.equity−first.equity)/first.equity` with `periodReturnPct`;
  % Y-axis; 0% baseline; period label.
- **New Next proxy** — `frontend/src/app/api/portfolio/return-series/route.ts` (the proxy layer is
  per-route; this must be hand-written).
- **Tab reconciliation** — header tabs are `1W/1M/3M/YTD/1Y/ALL`; EquityCurveCard's are
  `1M/3M/6M/1Y/ALL`. The return-series endpoint must support **1W and YTD**; unify on the header's
  set (drop or keep 6M as a decision in the plan).
- **`frontend/src/components/dashboard/HoldingsTable.tsx`, `frontend/src/app/portfolio/positions/page.tsx`,
  `frontend/src/components/dashboard/CryptoSection.tsx`** — drop market value ($), P/L ($), day
  change ($). Show % weight (`portfolioDiversity`), P/L % (`openPnlPercent`), day %
  (`dayChangePercent`). **Keep current price, quantity, and average cost per share** (visible +
  accurate). Default sort by weight desc. Sector breakdown shows % only.
- **`frontend/src/components/dashboard/DailyMoversTable.tsx`, `…/TopMovers.tsx`** — **already
  percent-only** (Symbol/Price/Day%/Week%); no $ change is rendered. Action = *verify* no $ change
  renders (the `MoverItem.dayChange` $ field exists in the type but is unrendered).
- **`frontend/src/components/dashboard/PortfolioRiskCard.tsx`** — render VaR as the new
  `var_95_1d_pct` / `var_95_5d_pct`. HHI / diversification / sector % unchanged.
- **`frontend/src/components/trade/BlossomTradeCard.tsx`, `…/activity/ActivityFeed.tsx`,
  `…/dashboard/TradeRecap.tsx`** — keep trade notional $, price, shares, realized P/L %, portfolio
  %. Hide standalone realized P/L $, unrealized P/L $, position P/L $. **(Cross-project rule — see
  Project B reconciliation: realized P/L $ is treated as a *derived* dollar and hidden; the
  Project B track-record panel shows realized P/L as **% only** to stay consistent.)**
- **`frontend/src/components/dashboard/RecentOrders.tsx`** — unchanged (price/total are factual).
- **Stock detail `frontend/src/components/stock/RobinhoodPositionCard.tsx`** — mirror the holdings
  table: drop market value $, P/L $, today $; show % weight, P/L %, today %; keep price, quantity,
  and avg cost per share. `RobinhoodStockHeader` (stock price) and `StockChart` $ axis unchanged
  (factual stock prices).

## Clarity requirement

A caption + (i) tooltip near the hero and the curve, wording ~ *"Performance of the stocks you
currently hold, repriced over this period — not your actual account history."*

## Out of scope

Removing `cash`/`buyingPower` from the API; removing `/portfolio/equity-curve`; factual stock
prices, the OHLCV chart $ axis, fundamentals $ (market cap / EPS); individual trade notional $ and
order totals; Project B.

## Testing

- **Backend** (`pytest -m "not openai and not integration"`): return-series normalization
  (`return[t₀] = 0`); flow-free property (a mid-window deposit/new-buy doesn't change the number);
  weight renormalization for short-history holdings; **all-crypto** and mixed equity+crypto
  baskets; `ALL` window with differing histories; empty/single-holding portfolios; bucket
  filtering. Risk report includes `var_95_1d_pct`/`var_95_5d_pct`.
- **Frontend:** $ totals/values/P&L$ no longer render in reframed components; % weight/return
  render; avg cost per share still renders; hero matches the selected tab and equals the
  return-series value; VaR shows %.

## Open items for review

- The UI component mapping is proposed; confirm during review.
- Exact tooltip wording.
- Tab set unification (keep EquityCurveCard's 6M, or standardize on the header's set).
