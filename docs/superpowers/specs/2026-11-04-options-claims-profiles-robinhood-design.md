# Covered calls, grounded thesis claims, thesis profiles, Robinhood MCP — Design

- **Date:** 2026-11-04
- **Status:** Draft, pending Qais's review
- **Order of work (Qais's):** 1 Covered calls → 2 openwiki ideas → 3 Thesis profiles for the bigger
  positions → 4 Robinhood Trading MCP. Each part ships on its own branch and is usable alone.

## Why

Qais wants the repo to (1) understand and help him reason about covered calls the way the AQR paper
does (*Israelov & Nielsen, "Covered Call Strategies: One Fact and Eight Myths," FAJ 2014*, which he
posted in `#llm-portfolio-dump` on 2026-08-13), (2) borrow what is useful from
`langchain-ai/openwiki`, (3) finally produce thesis profiles for his biggest holdings, and
(4) connect Robinhood's Trading MCP for research while making it impossible for anything to place a
real order without him.

## What the recon found (2026-11-04)

- **The paper's myths appear in his own posts.** AMD 2026-02-02 "selling a $260 call… $40 premium…
  protecting $40 downside" (Myth 2); NBIS 2025-06-16 "pull 3–5% monthly yield" and YieldMax
  2025-05-30 "income generating play" (Myths 3/4); INTC 2026-05-18 "good candidate for selling covered
  calls rn" with no volatility view. Two posts frame it correctly as a vol view: GOOGL 2025-07-14
  "$180 straddle… $11 feels underpriced", and 2026-07-21 "market is primed for selling premiums".
- **He has never written an option in a tracked account.** All ~500 option orders are `BUY_OPEN` /
  `SELL_CLOSE`; zero sell-to-open.
- **No current holding can carry a covered call.** Largest is NVDA at 3.42 shares; a contract needs
  100. Top holdings by current rows: NVDA, MSFT, GOOGL, TSLA, AMZN, DKNG, META, HOOD, UBER.
- **The parser can't represent short options.** INTC "selling covered calls" parsed as
  `direction=bearish, action=sell, option_type=call`; GOOGL straddle parsed with `option_type=null`;
  AMD "September" got `expiry=null`. There is no field for long vs short, or for a multi-leg strategy.
- **Nothing fetches option chains.** `yfinance` is already a dependency; nothing uses `option_chain`.
- **Thesis-profile backend is fully built but never run.** Migration 072, `app/routes/profiles.py`
  (CRUD + revisions, queue, autofill, interview, synthesize), `app/track_record.py`. 0 rows.
- **Position data is unreliable.** `positions` keeps rows for closed positions (Individual account has
  210 rows, oldest sync 2026-03-11; TSM/PLTR/CRCL/COHR still show). Even latest-sync rows sum to ~$8.2k
  while `accounts.total_equity` for the two connected accounts sums to ~$4.5k. Unexplained.
- **SnapTrade only connects Robinhood** (Individual, Roth IRA, checking, savings, credit card). No
  repo code calls any order-placing API today (grep for `place_order`/`TradingApi`/etc.: none).
- **Robinhood Trading MCP (docs read 2026-11-04):** HTTP at `https://agent.robinhood.com/mcp/trading`.
  Reads *all* Robinhood accounts (positions, balances, tax lots, realized P&L, order history, option
  chains/quotes/historicals, fundamentals, earnings, analyst ratings, news, SEC filings, Level 2).
  Trades *only* in a dedicated MCP/Agentic account opened during onboarding. Named write tools include
  `place_equity_order`, `cancel_equity_order`, `place_option_order`, `exercise_option`,
  `place_crypto_order`, `cancel_crypto_order`, `place_advanced_order`, `cancel_advanced_order`.
  **Trade approvals default OFF for external MCP accounts** ("still rolling out"). No multi-leg
  option orders.
- **Working copies:** the nested clone `LLM-portfolio-project\LLM-portfolio-project` is current
  (= GitHub `main`, 2026-07-22). The outer folder is a ~March 2026 copy with a broken `.git`; it holds
  the only `.env`. Build in the nested clone.

## Goals

1. The repo can **interpret** covered-call talk correctly, **reason** about whether a specific covered
   call is a good fit (with the paper's framing), and **help implement** one (strike/expiry candidates,
   what to watch) — without ever placing it.
2. Thesis claims are **grounded in evidence and re-checked**, borrowing openwiki's "grounded claims"
   idea; repo docs for agents get a lightweight freshness check.
3. Draft thesis profiles exist for the top holdings, built from data + his own Discord words, ready for
   a walkthrough where he confirms or corrects them.
4. Robinhood MCP is connected for research, its capabilities are documented with a SnapTrade
   keep/replace verdict, and order placement is blocked at several independent layers, with a
   documented path to a future, deliberate order feature.

## Non-goals

- Placing, staging, or cancelling any real order (now). Multi-leg option tooling.
- Frontend work (the Next.js app in `LLM-portfolio-frontend`). Backend, API, bot command and CLI only.
- Running openwiki itself (needs Node 22, not installed). We borrow ideas, not the tool.
- Replacing SnapTrade in this round; we only produce the verdict.

## Anti-goals (would be failure even if it "works")

- Anything in the repo or an agent session can send an order to Robinhood.
- The tool calls option premium "income" or "downside protection," or recommends a covered call
  purely because premium is high.
- Profiles get marked `active` without Qais reviewing them, or contain invented levels/claims.
- A bulk re-parse or profile build silently spends meaningful OpenAI money.

## Constraints

- Python 3.12 locally (repo `.venv` is broken; pyproject says ≥3.11). Postgres via Supabase pooler.
- Tests: `pytest -m "not openai and not integration"` must stay green; new LLM tests marked `openai`.
- Migrations follow `schema/NNN_*.sql` numbering (next free: 077) and `scripts/verify_database.py`.
- Live data is only what SnapTrade + Databento already provide; option chains from `yfinance` (delayed,
  free). Robinhood MCP data is only reachable inside an agent session, not from the EC2 pipeline.

---

## Part 1 — Covered calls

### 1a. Knowledge pack
- `docs/knowledge/options/covered-calls.md`: the one fact (long equity + short volatility), the eight
  myths each with a one-line correction, the decision checklist (below), and the paper's stylized
  numbers. Source cited.
- `src/options/knowledge.py`: a compact (~500-token) version for prompts. Injected into:
  the ticker chat route (`app/routes/chat.py`) when the question or the ticker's recent ideas carry the
  `OPTIONS` label; the profile synthesize prompt for the options section (Part 3); and a short rule
  block in the parser prompt (1b).

**Decision checklist the engine and prompts use:**
1. Do you hold ≥100 shares (or will you)? If not, it's not writable — say so plainly.
2. Is implied vol rich vs. expected realized vol (the volatility risk premium)? No view on vol → no
   reason to sell options.
3. Are you comfortable with less upside and nearly full downside? (Downside beta stays high.)
4. Earnings / ex-dividend inside the window? Flag assignment and gap risk.
5. Is the sale a plan or an obligation? (Myth 7.) Name the price you're contractually committing to.

### 1b. Parser understands short options and strategies
- Schema (`src/nlp/schemas.py`): add `option_side: long|short|null` and
  `option_strategy: single|covered_call|cash_secured_put|straddle|strangle|vertical|calendar|wheel|
  leaps|unknown|null`. Rule in the prompt: a covered call's `direction` reflects the view on the
  stock (long equity), never "bearish" just because a call is sold.
- Expiry: resolve month-only expiries ("September") to the standard monthly expiry (3rd Friday) of the
  next such month after the message date, and set a flag `expiry_inferred=true` in `raw_json`.
- Migration `077_parsed_ideas_option_strategy.sql`: two nullable columns + CHECKs; bump
  `OPENAI_PROMPT_VERSION`.
- Regression fixtures (`tests/fixtures/parser_regression.jsonl`): the AMD, INTC, GOOGL-straddle and
  NBIS-wheel messages with expected fields.
- Re-parse only ideas already labeled `OPTIONS` via the existing reparse path, **after** Qais OKs the
  spend (count shown first, dry run default).

### 1c. Covered-call fit engine
`src/options/` — pure functions, no I/O in the math:
- `pricing.py`: Black–Scholes price/delta/vega; implied-vol solve.
- `vol.py`: realized vol (20d/60d close-to-close from `ohlcv_daily`) and a simple forecast (EWMA).
- `chains.py`: `OptionChainSource` interface; `YFinanceChainSource` implementation (cached ≤15 min).
  A `RobinhoodMCPChainSource` is documented but not implemented (MCP isn't callable from the server).
- `covered_call.py`: `evaluate(symbol, expiry=None, strikes=None) -> CoveredCallReport`:
  - **Feasibility:** current shares (from the fixed current-positions helper, Part 3), contracts
    writable = floor(shares/100). If 0: verdict `not_writable`, with shares/$ needed to reach 100 and
    the cash a cash-secured put at the same strike would tie up. Hypothetical analysis only with
    `hypothetical=True`.
  - **Per candidate (expiries 14–60 DTE; strikes ATM to ~10% OTM):** premium (mid), delta, the paper's
    decomposition — equity-exposure return ≈ delta × expected excess return, **volatility premium $ =
    premium − BS price at forecast realized vol**, annualized VRP %, upside cap %, breakeven,
    earnings-in-window and ex-div flags, liquidity (bid-ask %, open interest).
  - **Verdict:** `good_fit | marginal | poor_fit | not_writable` from: VRP > 0 and meaningful, liquidity
    OK, no earnings in window (or flagged), and his stated view (from the profile, if any).
  - **Myth flags:** when the triggering text (Discord idea or chat question) frames premium as income,
    yield or protection, attach the matching myth correction.
- Surfaces: `GET /stocks/{ticker}/options/covered-call` (new `app/routes/options.py`, root-mounted
  before `stocks.py`'s catch-all), Discord bot `!cc TICKER [expiry]`, and the profile's options section.
- **Tests:** Black–Scholes against known values; the paper's stylized example reproduced (S=100,
  1 month, IV 18%, RV 16%, ATM → premium ≈ $2.07, vol premium ≈ $0.23, ≈2.76%/yr VRP); feasibility
  with <100 shares; chain source mocked.

## Part 2 — openwiki ideas

### 2a. Grounded thesis claims (openwiki "Grounded Claims," applied to theses)
- Migration `078_thesis_claims.sql`: `thesis_claims(id, profile_id → stock_thesis_profiles,
  claim_text, claim_type ∈ {price_level, catalyst, fundamental, position, sentiment, options},
  evidence jsonb[] [{kind: discord_message|ohlcv|filing|news|order|position|option_chain, ref,
  value_at_capture, captured_at}], check_rule jsonb null, status ∈ {fresh, needs_review, broken,
  retired}, last_checked_at, created_at)`. RLS on.
- Synthesize (Part 3) emits claims alongside the thesis; each must cite ≥1 evidence item or it is
  dropped (no unsupported claims — matches the existing reflect pass).
- `check_rule` types for v1: `price_above`, `price_below`, `date_passed` (catalyst), `position_open`,
  `position_closed`, `vrp_sign` (options). Others stay `check_rule=null` and age to `needs_review`
  after `PROFILE_STALE_DAYS`.
- `scripts/check_thesis_claims.py` (+ a step in `scripts/nightly_pipeline.py`): evaluates rules,
  updates status. The review queue gains a top tier: **profiles with broken claims**.

### 2b. Living docs for agents (openwiki "living wiki")
- Front matter `sources:` (file globs) on `docs/CODEBASE_MAP.md`, `docs/ARCHITECTURE.md`,
  `docs/api-reference.md`, and the schema/routes sections of `CLAUDE.md`/`AGENTS.md` (as a comment
  block).
- `scripts/check_docs_fresh.py`: for each doc, compare the git last-commit time of its sources vs the
  doc; print stale docs and the changed files. Run in CI as a **warning** (non-blocking).
- An `AGENTS.md` "how to navigate" block listing which doc answers which question (openwiki's
  generated block idea, written by hand).

## Part 3 — Thesis profiles for the bigger positions

### 3a. Prerequisite: trustworthy current positions
- Shared helper `src/position_truth.py: current_positions()` — rows from each account's latest sync
  only, quantity > 0. Used by the queue, profiles, and the covered-call engine.
- Fix the sync so closed positions stop lingering: in `snaptrade_collector.py`, after a successful
  account sync, delete (or mark closed) rows for that account not present in the new snapshot.
- Investigate and document the $8.2k vs $4.5k mismatch (likely `equity` semantics or duplicate rows);
  fix if it's ours. If Robinhood MCP is connected, reconcile against `get_portfolio` once, by hand.

### 3a-bis. One profile per stock (Qais, 2026-11-04)
- Each symbol has exactly **one** live profile, regardless of which accounts hold it. Migration adds a
  partial unique index `UNIQUE (UPPER(symbol)) WHERE status <> 'archived'`. The row's `bucket` is set
  to the bucket holding the larger position (kept as a label only).
- Track record and position data aggregate **across all accounts** (`compute_stock_track_record(symbol,
  None)`); the profile shows the per-account split (e.g., Individual 2.1 sh / Roth 1.3 sh).
- API: `bucket` becomes optional on profile routes; when omitted, resolve to the symbol's single
  profile. Existing bucket-scoped behavior stays for back-compat.

### 3a-ter. What a profile contains (the "extremely useful" bar)
Every section is evidence-linked; anything without a source is marked as an inference.
1. **Snapshot** — shares and weight (per account + total), cost basis, unrealized %, 52-week range,
   1m/3m/1y returns, 30/90d realized vol, next earnings date.
2. **Thesis** — one paragraph in his voice; **conviction 1–5** with rationale; **sizing check** (flag
   when weight and conviction disagree, e.g., conviction 5 at 1% weight).
3. **Bull case / bear case** — as grounded claims (Part 2a).
4. **Catalysts** — dated and checkable.
5. **Levels** — add zone, trim/target, invalidation — taken from his own posted levels where they exist
   (cited message), otherwise derived and labeled as such.
6. **Kill criteria** — "what would make me sell," explicit and checkable.
7. **His timeline** — every Discord mention of the ticker, condensed chronologically, showing how his
   view evolved.
8. **Said vs. did** — ideas vs. his actual trades within ±10 days; contradictions surfaced.
9. **Track record** — trades, win rate, realized %, average hold, entry quality.
10. **Options lens** — covered-call / cash-secured-put feasibility and the volatility-premium read.
11. **Outside view** — fundamentals snapshot, analyst consensus/ratings, recent news.
12. **Open questions for Qais** — what only he can answer, carried into the walkthrough.
Storage: existing columns where they fit (`thesis`, `conviction`, `bull_case`, `bear_case`,
`catalysts`, `risks`, `levels`, `horizon`, `tags`); new nullable columns `kill_criteria text`,
`sizing_note text`, `timeline_json jsonb`, `said_vs_did_json jsonb`, `options_lens_json jsonb`,
`outside_view_json jsonb`, `open_questions jsonb` (migration 079). Claims live in `thesis_claims`.

### 3a-quater. Cost: session engine first (Qais: "keep it cheap, heavy lifting by Claude in sessions")
- The builder has two engines. **`--engine session` (default):** the script assembles a deterministic
  context bundle per stock (all data sections above, his messages with ids, trades, prices, option
  chain) into `data/profile_builds/<SYMBOL>/context.md` + `context.json` with **no LLM calls**; Claude
  writes the profile in-session as `profile.json`; `--import` validates it against the profile schema
  (incl. "every claim cites evidence") and saves it as `draft`. **`--engine openai`:** the existing
  interview/synthesize endpoints, used only when running unattended, after a printed token/$ estimate.
- In session mode the 5-agent consensus pipeline is **not** triggered (cache read only); Claude covers
  the outside view from data + Robinhood MCP reads when connected.
- OpenAI spend (re-parse of `OPTIONS` ideas, any `--engine openai` run) always prints count + $ estimate
  first and proceeds only after Qais OKs it.

### 3b. Batch builder
`scripts/build_thesis_profiles.py --top 9 | --symbols NVDA,MSFT [--dry-run] [--max-cost-usd 2]`:
1. Pick symbols from `current_positions()` by equity.
2. For each: run existing **autofill** (track record, news, consensus, risk, ideas digest) plus the
   **covered-call report** (Part 1).
3. Run existing **interview** to get 3–5 questions.
4. **New — pre-answer from his own words:** an LLM drafts each answer only from his Discord messages
   about the ticker, citing `message_id`s; answers with no supporting message are left blank and
   marked `needs_qais`.
5. Run existing **synthesize** (3-pass) and emit grounded claims (Part 2a).
6. Save with `status='draft'`, `interview_json` holding questions + drafted answers + citations.
   Never `active`.
- Cost guard: estimate tokens before running; stop when `--max-cost-usd` would be exceeded.
- Output: a markdown summary per symbol (thesis, conviction, open questions, broken/unsupported
  claims, covered-call verdict) for the walkthrough.

### 3c. "Smart" additions to the profile
- **Said vs did:** for each idea he posted, what he traded within ±10 days (from `orders`), surfaced
  as contradictions for the interview ("you called NVDA a buy at $175 on 8/18, then sold on 8/22").
- **Options lens:** the covered-call verdict and the paper's framing, so the profile says whether the
  stock is a vol-selling candidate at all.
- **Freshness:** profile shows claim statuses; broken claims pull it into the queue.

### 3d. Walkthrough
A conversational pass with Qais per symbol: confirm/edit drafted answers, resolve `needs_qais`,
re-synthesize, then he chooses `active`. (This is the "walk through and ask questions" he wanted.)

## Part 4 — Robinhood Trading MCP

### 4a. Connection
- Add at **project scope** in the nested clone: `.mcp.json` entry
  `robinhood-trading → {type: http, url: https://agent.robinhood.com/mcp/trading}`. No secrets.
- Qais authenticates via `/mcp` in an interactive Claude Code session (cannot be done by an agent).
  Onboarding opens a Robinhood **MCP/Agentic account**; that account is the only one it can trade in.
- After auth: list the real tool inventory and record it in the capability doc (4c).

### 4b. Guardrails — four independent layers
1. **Robinhood side:** keep the MCP account **unfunded** ($0 → nothing can execute). Turn trade
   approvals ON for it when Robinhood ships that for MCP accounts.
2. **Claude Code permissions (user-level `~/.claude/settings.json` and project
   `.claude/settings.json`):** `deny` every known write tool:
   `mcp__robinhood-trading__place_equity_order`, `…cancel_equity_order`, `…place_option_order`,
   `…exercise_option`, `…place_crypto_order`, `…cancel_crypto_order`, `…place_advanced_order`,
   `…cancel_advanced_order`.
3. **PreToolUse hook (user-level), allowlist-based:** for any MCP server whose name contains
   `robinhood`, allow only tools whose name starts with `get_`, `list_`, `search_`, `review_`,
   `preview_`; block everything else with a message. Catches tools Robinhood adds later. Includes a
   test script that feeds the hook sample tool names.
4. **Repo code:** `src/trading_guard.py` with `assert_live_trading_disabled()`; env
   `LIVE_TRADING_ENABLED` defaults false and nothing in the codebase sets it. `tests/test_no_order_placement.py`
   scans `src/`, `app/`, `scripts/` for order-placing identifiers (Robinhood MCP write-tool names,
   SnapTrade trading endpoints, `robin_stocks` order functions) and fails if found outside
   `trading_guard.py`.

### 4c. Capability doc + SnapTrade verdict — `docs/integrations/robinhood-mcp.md`
- Tool inventory (from the live list), each tagged read/write, blocked/allowed, and which repo feature
  could use it (e.g., `get_option_chains` → covered-call engine in agent sessions; tax lots → track
  record; `get_realized_pnl` → reconciliation; earnings/analyst ratings → profile autofill).
- **Preliminary verdict: keep SnapTrade** for the unattended EC2 sync and webhook (the MCP needs an
  interactive OAuth session and is built for agents). Use the MCP for agent-session research and
  reconciliation. Revisit if Robinhood offers headless tokens; test once after auth whether the
  MCP token can be used non-interactively.

### 4d. Future order feature (documented only)
Path if Qais later wants it: separate branch; MCP account stays the only target; flow =
`review_*_order` → show the review to Qais → explicit per-order confirmation in chat → place; per-order
and daily dollar caps; full audit log table; the hook switches from block to "ask" for exactly
`place_equity_order` and nothing else. Not built now.

---

## Decided by Qais
- Order of work: covered calls → openwiki ideas → thesis profiles → Robinhood MCP.
- Load finance channels only into Supabase (done 2026-11-04).
- Nothing may place real orders now; an order feature may come later.

## Claude's calls (check these)
- Backend/API/bot/CLI only; no frontend this round.
- Option chains from `yfinance` (free, delayed) behind an interface; Robinhood MCP chains only in
  agent sessions.
- Profiles built for the top 9 by current equity, saved as `draft` only.
- Borrow openwiki's ideas (grounded claims, living docs) rather than install it.
- MCP added at project scope; guard hook + deny list at user level so it holds anywhere.
- Fix lingering closed-position rows as part of Part 3.

- One profile per stock (3a-bis).
- OpenAI spend OK once an estimate is shown; keep it cheap; Claude does heavy lifting in sessions
  (3a-quater).
- Install Node in case openwiki is needed (done 2026-11-04: Node v26.13.0, npm 11.20.0).

## Done during design (2026-11-04)
- Robinhood MCP registered in `.mcp.json` (project scope); not yet authenticated.
- Guard layers 2 and 3 live in `~/.claude/settings.json` + `~/.claude/hooks/robinhood_readonly_guard.py`,
  pipe-tested. Capability doc: `docs/integrations/robinhood-mcp.md`.

## Open questions for Qais
None blocking. After first MCP sign-in: confirm the live tool list matches the doc.

## Left to the builder
File/module names inside the stated folders, chain-candidate grid details, EWMA parameters, the exact
claim-extraction prompt, CLI output formatting.
