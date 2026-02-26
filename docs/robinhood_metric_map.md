# Robinhood Metric Mapping Reference

Source-of-truth document mapping each Robinhood UI label to our backend field, formula, data source, and known gaps.

## Account-Level Metrics

| Robinhood Label | Our API Field | Formula | Data Source | Edge Cases |
|---|---|---|---|---|
| Your investing | `summary.totalValue` | totalEquity + max(cash, 0) | positions + account_balances | Margin: negative cash excluded from total |
| Today's return ($) | `summary.dayChange` | SUM((currentPrice - prevClose) * qty) | ohlcv_daily prev close + yfinance fallback | Null if market closed and no prev close |
| Today's return (%) | `summary.dayChangePercent` | dayChange / (totalValue - dayChange) * 100 | Computed | RH uses prev-day total as denominator; ours approximates |
| Total return ($) | `summary.unrealizedPL` | totalEquity - totalCost | positions.average_buy_price | Crypto: avg_cost may be stale |
| Total return (%) | `summary.unrealizedPLPercent` | unrealizedPL / totalCost * 100 | Computed | Zero-cost positions produce 0% |
| Cash | `summary.cashBalance` | SUM(account_balances.cash) | account_balances | Can be negative (margin debit) |
| Buying power | `summary.buyingPower` **(NEW)** | SUM(account_balances.buying_power) | account_balances | May differ from cash for margin accounts |
| Individual investing | `summary.totalEquity` | SUM(position.equity) | Computed | Same as "Your investing" minus cash |

## Position-Level Metrics

| Robinhood Label | Our API Field | Formula | Data Source | Edge Cases |
|---|---|---|---|---|
| Shares | `position.quantity` | Direct | positions.quantity | Fractional shares preserved to 4 decimals |
| Average cost | `position.averageBuyPrice` | Direct | positions.average_buy_price | SnapTrade average_purchase_price |
| Market value | `position.equity` | quantity * currentPrice | Computed | Price cascade: Databento > SnapTrade > yfinance > avgCost |
| Today's return ($) | `position.dayChange` | (currentPrice - prevClose) * quantity | ohlcv_daily + yfinance | Null when no previous close available |
| Today's return (%) | `position.dayChangePercent` | (currentPrice - prevClose) / prevClose * 100 | Computed | Per-share %, not position-dollar weighted |
| Total return ($) | `position.openPnl` | equity - (quantity * averageBuyPrice) | Computed | |
| Total return (%) | `position.openPnlPercent` | openPnl / costBasis * 100 | Computed | Zero cost basis produces 0% |
| Portfolio diversity | `position.portfolioDiversity` **(NEW)** | equity / totalEquity * 100 | Computed | Sum may not be exactly 100% due to rounding |

## Price Source Cascade

1. **Databento** (ohlcv_daily) — primary, updated nightly
2. **SnapTrade** (positions.price) — fallback, updated on sync
3. **yfinance** (market_data_service) — second fallback, 5-min TTL cache
4. **Average buy price** — last resort (stale but non-zero)

## Known Gaps and Discrepancies

### Crypto Positions
- Databento does NOT cover crypto (XRP, BTC, etc.)
- Price falls back to SnapTrade `positions.price` or yfinance
- Day change may be null if yfinance also fails

### Day Change Timing
- Databento prices are end-of-day; during market hours, "today's return" uses yesterday's close vs yesterday's close = 0 change
- Robinhood uses real-time intraday prices
- Mitigation: yfinance provides intraday `regularMarketPrice` as fallback

### Margin / Cash Display
- Robinhood shows "Buying power" as a first-class metric
- Our system returns `cashBalance` which can be negative for margin
- `buyingPower` from `account_balances` is surfaced as a new field

### Historical Portfolio Value
- Robinhood shows "Your investing" as a time-series chart (1D/1W/1M/1Y/ALL)
- We have NO historical portfolio-value snapshots
- Would require a new `portfolio_snapshots` table populated by nightly pipeline
- OUT OF SCOPE for this iteration — change line shows dayChange for short ranges and totalPnl for ALL
