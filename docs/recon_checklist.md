# Portfolio Reconciliation QA Checklist

Step-by-step guide for verifying our portfolio metrics against Robinhood app screenshots.

## Prerequisites

- [ ] SnapTrade sync completed recently (check `summary.lastSync`)
- [ ] Market is closed (compare end-of-day values, not intraday)
- [ ] Robinhood app open with the same account
- [ ] Our app loaded with `?recon=1` to show the debug panel

## Account-Level Checks

### 1. "Your Investing" (Total Portfolio Value)

- [ ] Open Robinhood main screen, note "Your investing" value
- [ ] Compare to our `summary.totalValue`
- [ ] Tolerance: within $5 (rounding + timing)
- [ ] If large discrepancy: check recon panel `cashForTotal` and `totalEquityComputed`
- [ ] Common causes: pending orders, unsettled trades, margin differences

### 2. "Today's Return"

- [ ] Note Robinhood "Today's return" $ and %
- [ ] Compare to our `summary.dayChange` and `summary.dayChangePercent`
- [ ] Tolerance: within $1 and 0.1% after market close
- [ ] If mismatch: check recon panel `priceSourceBreakdown` — positions using yfinance fallback may have different prev close
- [ ] Known issue: crypto positions may show different day change due to 24h vs market-hours

### 3. "Total Return"

- [ ] Note Robinhood total return $ and %
- [ ] Compare to our `summary.unrealizedPL` and `summary.unrealizedPLPercent`
- [ ] Tolerance: within 1% of value
- [ ] If mismatch: likely average cost difference — compare position-level avg cost

### 4. Cash / Buying Power

- [ ] Note Robinhood "Cash" and "Buying power"
- [ ] Compare to our `summary.cashBalance` and `summary.buyingPower`
- [ ] For margin accounts: cash may be negative, buying power may differ significantly

## Position-Level Checks

Pick 3-5 positions including one crypto if applicable.

For each position:

- [ ] **Shares**: Compare quantity (should be exact match)
- [ ] **Average cost**: Compare (should match to the penny; if not, SnapTrade may not have updated)
- [ ] **Market value**: Compare (timing differences expected during market hours)
- [ ] **Today's return**: Compare $ and %
  - [ ] Check recon panel price source for the symbol
  - [ ] If "avgcost": day change will be $0 (known gap)
- [ ] **Total return**: Compare $ and %
- [ ] **Portfolio diversity %**: Compare to Robinhood "Portfolio diversity"
  - [ ] Our formula: position.equity / summary.totalEquity * 100

### Crypto Position Special Check

- [ ] Verify crypto price source is not "avgcost" (should be snaptrade or yfinance)
- [ ] If using avgcost: day change and total return will be incorrect
- [ ] Check if recon panel shows a yfinance price for the symbol

## Edge Case Scenarios

### Recently Executed Trade

- [ ] Sync after trade execution
- [ ] Verify new position appears
- [ ] Verify average cost updated (may take 1 sync cycle)
- [ ] Verify total cost basis changed

### Market Closed (Weekend)

- [ ] Day change should be $0 / 0%
- [ ] Total return should still be accurate
- [ ] Prices should reflect Friday's close

### Margin Account

- [ ] Cash balance may be negative
- [ ] totalValue = totalEquity + max(cash, 0) — negative cash is NOT subtracted
- [ ] Compare Robinhood "Individual investing" to our `summary.totalEquity`

### Fractional Shares

- [ ] Verify fractional quantities preserved (e.g., 2.5 shares)
- [ ] Verify market value computation uses exact fractional quantity

## Sign-Off

| Field | Value |
|---|---|
| Date | |
| Tester | |
| Positions checked | / |
| Account totals within tolerance | Yes / No |
| Open issues | |
