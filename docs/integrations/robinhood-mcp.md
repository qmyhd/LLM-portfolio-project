# Robinhood Trading MCP — setup, capabilities, guardrails

- **Last verified:** 2026-11-04. The tool list below is the **live list** after sign-in (85 tools exposed
  to the session plus the deny-listed write tools). Robinhood's own docs are linked at the bottom.
- **Status:** registered in `.mcp.json` (project scope), **authenticated and connected**. **Read-only by
  policy**, and the guard lives in this repo (see "Guardrails").
- **Machine-readable snapshot:** [`robinhood-mcp-tools.json`](robinhood-mcp-tools.json), which pins every
  tool name with its read/write verdict. `tests/test_robinhood_guard.py` fails if the hook or deny rules
  drift from it.

## Accounts seen by the MCP (2026-11-04)

| Account | Type | Brokerage trading type | Agent can trade? |
| --- | --- | --- | --- |
| QaisIndividual ••0048 (default) | individual | margin (options level 3) | no — read-only |
| MCP ••6124 | individual | cash | **yes — the only agent-tradable account** |
| Roth IRA ••9003 | ira_roth | cash | no — read-only |

⚠️ The MCP account holds **$10 cash** (buying power $10). Policy below says keep it at **$0**. Withdraw it
if you want the unfunded-account layer to be fully effective.

## What it is

An MCP server Robinhood hosts at `https://agent.robinhood.com/mcp/trading` (HTTP transport). It lets an
external AI agent (Claude Code here) read your Robinhood data and — if allowed — trade in one
dedicated account. It is separate from:

- **Robinhood Agents** — Robinhood's own in-app agents (mobile only, their model choice, e.g. GPT-6 Luna).
  Not used here.
- **Agent apps** — paid add-ons for in-app agents only. Not used here.
- **Robinhood Banking MCP / Agentic Credit Card** — a different MCP that lets an agent spend with a
  virtual Gold Card. **Do not connect it.** Nothing in this project needs it.

## Account model (important)

- Signing in opens a new **Robinhood MCP account**: a self-directed individual investing account just
  for the agent. It counts toward Robinhood's 10-account cap and needs a primary individual account
  in good standing.
- **Reads cover ALL your Robinhood accounts** (Individual, Roth IRA, etc.), including account
  numbers, positions, balances, order and transaction history.
- **Trades can only happen in the MCP account.** Your Individual and Roth cannot be traded by it.
- During onboarding you pick **cash** or **limited margin** (preselected). Limited margin gives no
  borrowing; it only lets unsettled sale proceeds be reused. **Choose cash.**
- **Trade approvals:** default **OFF for external MCP accounts** (Robinhood: "still rolling out").
  With approvals off, the agent can place eligible orders without asking. Turn approvals **on** the
  moment Robinhood offers it for MCP accounts.

## What it can read

| Area | Data |
|---|---|
| Accounts & portfolio | balances, buying power, total value, positions, realized P&L, trade history |
| Equities & crypto | positions, **tax lots**, quotes, order history, tradability |
| Options | **option chains**, quotes, historicals, positions, order history |
| Market data | historical bars, fundamentals, Level 2 order book, technical indicators, **earnings**, **analyst ratings**, news, SEC filings, politician trades, indexes |
| Other | watchlists, scanners, alerts, Legend charting data |

## Tools (live list, 2026-11-04)

Prefix tool names with `mcp__robinhood-trading__` when calling them. The JSON snapshot is the source of truth.

### Read (63): allowed

| Area | Tools |
| --- | --- |
| Accounts & portfolio | `get_accounts`, `get_portfolio`, `get_realized_pnl`, `get_pnl_trade_history`, `get_limited_margin_upgrade_info`, `get_option_level_upgrade_info` |
| Banking & credit (read) | `get_bank_accounts`, `get_banking_transactions`, `get_credit_card_account`, `get_credit_transactions` |
| Equities | `get_equity_positions`, `get_equity_orders`, `get_equity_quotes`, `get_equity_historicals`, `get_equity_tax_lots`, `get_equity_tradability`, `get_equity_fundamentals`, `get_equity_analyst_ratings`, `get_equity_price_book`, `get_equity_technical_indicators`, `get_financials` |
| Options | `get_option_chains`, `get_option_instruments`, `get_option_quotes`, `get_option_historicals`, `get_option_positions`, `get_option_orders`, `get_option_watchlist` |
| Crypto | `get_crypto_positions`, `get_crypto_orders`, `get_crypto_quotes`, `get_currency_pairs`, `get_crypto_account_onboarding_info` |
| Market data | `get_indexes`, `get_index_quotes`, `get_index_historicals`, `get_earnings_calendar`, `get_earnings_results`, `get_politician_trades` |
| SEC filings | `get_sec_filing`, `get_sec_filing_index`, `get_sec_filing_facts`, `get_sec_filing_facts_catalog` |
| Watchlists & alerts | `get_watchlists`, `get_watchlist_items`, `get_popular_watchlists`, `get_alerts`, `get_alert_log` |
| Scanners | `get_scans`, `get_scanner_datapoints`, `get_scanner_filter_specs`, `preview_scan`, `run_scan` |
| Legend charts | `get_legend_charts`, `get_legend_layouts`, `get_legend_indicators`, `get_legend_indicator_catalog` |
| Trade approvals | `get_trade_approvals`, `get_trade_approval_setting` |
| Lookup | `search` (name → symbol / instrument_id / crypto pair / index id) |
| Dry-run previews (place nothing) | `review_equity_order`, `review_option_order`, `preview_crypto_order` |

### Write (22 seen live): blocked by the hook

| Kind | Tools |
| --- | --- |
| Order-affecting (also in deny rules) | `cancel_option_order`, `cancel_option_exercise` |
| Trade approvals | `decline_trade_approval` |
| Watchlists | `create_watchlist`, `update_watchlist`, `add_to_watchlist`, `remove_from_watchlist`, `add_option_to_watchlist`, `remove_option_from_watchlist`, `follow_watchlist`, `unfollow_watchlist` |
| Alerts | `create_alert`, `update_alert`, `delete_alert`, `mark_alerts_read` |
| Scanners | `create_scan`, `update_scan_config`, `update_scan_filters` |
| Legend charts | `add_legend_indicator`, `update_legend_indicator`, `remove_legend_indicator`, `set_legend_chart_settings` |

### Order tools: removed from the session by deny rules

`place_equity_order`, `cancel_equity_order`, `place_option_order`, `cancel_option_order`,
`exercise_option`, `cancel_option_exercise`, `place_crypto_order`, `cancel_crypto_order`,
`place_advanced_order`, `cancel_advanced_order`.

Deny rules hide these tools, so a live listing can't show which of them Robinhood actually serves.
Only the two `cancel_option_*` tools were seen live, before they were added to the deny list.
`search`'s own description refers to `place_equity_order`, so that tool exists. Robinhood's docs
mention `review_advanced_order`, but the live server doesn't expose it.

Order types it supports (if ever allowed): market (shares or dollars), limit, stop limit, stop market,
take-profit/stop-loss. **No multi-leg options.** Crypto: trade only (no transfer/stake/lend); not
available in some states (e.g., NY).

## Guardrails — four independent layers

1. **Unfunded account.** Keep the MCP account at **$0**. With nothing in it, no order can fill. This is
   the strongest layer and the only one Robinhood enforces.
2. **Claude Code deny rules**: the ten order tools listed above, removed from the session entirely.
   - Project scope (committed): `.claude/settings.json` → `permissions.deny`. Applies to anyone running
     Claude Code in this repo.
   - User scope (optional, Qais's machine): `~/.claude/settings.json` holds the original eight, so the
     guard also applies outside this repo.
3. **Read-only hook** (PreToolUse, matcher `mcp__.*[Rr]obinhood.*`): on any MCP server whose name
   contains "robinhood", only tools starting `get_`/`list_`/`search_`/`review_`/`preview_`, plus the
   exact names `search` and `run_scan`, may run. Everything else is denied, including tools Robinhood
   adds later. Fails closed (`onFailure: block`; unreadable input exits 2).
   - Canonical copy (committed): `.claude/hooks/robinhood_readonly_guard.py`, wired in
     `.claude/settings.json` as `python "$CLAUDE_PROJECT_DIR/.claude/hooks/robinhood_readonly_guard.py"`.
     It needs `python` on PATH. If Python is missing the hook errors, which **blocks** every Robinhood
     call (safe failure).
   - User copy: `~/.claude/hooks/robinhood_readonly_guard.py` (wired in `~/.claude/settings.json`).
     Keep it identical to the repo copy. Both hooks run, and a deny from either one wins.
   - `tests/test_robinhood_guard.py` checks every tool in `robinhood-mcp-tools.json` against the hook,
     checks that the deny rules match the snapshot, and checks fail-closed behaviour. It runs in CI.
   - Verified live 2026-11-04: `place_equity_order` can't even be loaded into the session (deny rule),
     and fed to the hook it returns `permissionDecision: deny`. `get_portfolio` and `search` ran fine.
   *Why this matters:* your Claude Code default permission mode is `auto`, which could otherwise run
   an MCP call without a prompt.
4. **Repo code** (planned, see design spec Part 4b): `src/trading_guard.py` +
   `tests/test_no_order_placement.py` so no code path in this repo can place orders. Today no repo code
   calls any order API (verified by grep 2026-11-04).

## What's in the repo

| File | Role |
| --- | --- |
| `.mcp.json` | Registers `robinhood-trading` (HTTP, `https://agent.robinhood.com/mcp/trading`) at project scope |
| `.claude/settings.json` | Pre-approves the server (`enabledMcpjsonServers`), sets the deny rules and wires the hook |
| `.claude/hooks/robinhood_readonly_guard.py` | Read-only PreToolUse hook (canonical copy) |
| `docs/integrations/robinhood-mcp-tools.json` | Pinned live tool list with read/write verdicts |
| `tests/test_robinhood_guard.py` | Keeps the hook, deny rules and snapshot in sync |

The OAuth token is **not** in the repo. Claude Code stores it per user, so each machine signs in once.

## Setup steps (new machine / fresh clone)

1. Open a terminal in the repo root and run `claude` (interactive; an agent can't do the sign-in).
2. The server is pre-approved via `.claude/settings.json`. If Claude Code still asks, approve it.
3. Type `/mcp` → select **robinhood-trading** → **Authenticate**. A browser window opens to Robinhood.
4. First sign-in only: complete MCP-account onboarding (name it, sign the account and agentic
   agreements, **deselect margin → cash account**, **do not fund it**). Already done for Qais (MCP ••6124).
5. `/mcp` should show robinhood-trading connected. Check with `pytest tests/test_robinhood_guard.py -q`.

## Refreshing the tool list

When Robinhood adds or renames tools: list the `mcp__robinhood-trading__*` tools in a session, update
`robinhood-mcp-tools.json` (put each new name in `read` or `write`) and the tables above, then run
the guard test. A new read tool whose name doesn't start with an allowed prefix needs an explicit
`ALLOWED_EXACT` entry in the hook. Add one only after reading its description to confirm it's
read-only.

To disconnect: `/mcp` → robinhood-trading → clear authentication, or `claude mcp remove
robinhood-trading -s project`. Robinhood says agents can be paused/disconnected anytime; contact
Robinhood support for anything on their side.

## What it means for this repo

| Need | Today | With the MCP |
|---|---|---|
| Nightly positions/orders sync (EC2, unattended) | SnapTrade | **Keep SnapTrade** — the MCP needs an interactive OAuth sign-in and is built for agent sessions |
| Position reconciliation (the $8.2k vs $4.5k mismatch) | none | `get_portfolio` / `get_equity_positions` in a session — authoritative cross-check |
| Covered-call engine: option chains / implied vol | none (planned: yfinance) | `get_option_chains` in sessions — real Robinhood chains |
| Thesis profiles: tax lots, realized P&L, earnings dates, analyst ratings | partial | in-session enrichment while building profiles |
| Placing orders | never | **never** (blocked); see "Future order feature" |

**SnapTrade verdict: keep it** for unattended sync. Revisit only if Robinhood offers non-interactive
tokens (check after first sign-in whether the session token can be reused headlessly — expected no).

## Future order feature (not built)

If wanted later: separate branch; only the MCP account; flow = `review_*` → show the review → explicit
per-order "yes" from Qais in chat → place. Per-order and daily dollar caps, an audit-log table, and the
hook changed from block to **ask** for `place_equity_order` only. Turn Robinhood trade approvals on
first. Fund the account with only what you're willing to let it use.

## Risks Robinhood states

You are responsible for every trade an agent places; agents can misread instructions or act on stale
data; Robinhood doesn't guarantee agent output; data shared with the AI provider is at your own risk;
options can lose value fast; crypto isn't FDIC/SIPC protected.

## Sources

- https://robinhood.com/us/en/support/articles/agentic-trading-overview/
- https://robinhood.com/us/en/support/articles/robinhood-agents-overview/
- https://robinhood.com/us/en/support/articles/setting-up-an-agent/
- https://robinhood.com/us/en/support/articles/trading-with-your-agent/
- https://robinhood.com/us/en/support/articles/agent-apps/
- https://robinhood.com/us/en/support/articles/agentic-credit-card/
- https://robinhood.com/us/en/support/articles/using-gpt-luna/
