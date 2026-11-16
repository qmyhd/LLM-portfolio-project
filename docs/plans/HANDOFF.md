# Handoff: where the LLM-portfolio work stands (written 11/16/2026)

Read this first when picking the work up on another machine or in a new Claude chat. It replaces the chat
history: everything a new session needs is in this file or in the files it points to.

**To start a new chat, say:** "Read `docs/plans/HANDOFF.md` in the LLM-portfolio-project repo and continue from it."

## The four files that hold the state

| File | What it is |
|---|---|
| `docs/plans/2026-11-12-next-round-backlog.md` | The master list: every request Qais made, sections A to G, progress board, items carried forward |
| `docs/superpowers/specs/2026-11-12-roles-privacy-options-cost-design.md` | The approved design for section A (roles, %-only view, options, AI cap) |
| `docs/superpowers/plans/2026-11-12-roles-approval-plan.md` | Plan 1 of 4: the build plan and the rollout steps (Task 12) |
| `docs/plans/2026-11-13-roles-build-ledger.md` | The build ledger: every ruling made during the build and every finding deferred as minor |

## Where things are

- **Live now (since 11/12):** the security hardening. Backend `459417f`, frontend `0f86fbe`. The server runs with
  `ENVIRONMENT=production`; nginx allows PATCH; the nightly pipeline is on.
- **Built, reviewed, not live:** Plan 1 (four roles, sign-in approval, password accounts, Users page, Discord
  alerts), on branch `feat/roles-approval` in both repos.
  - Backend head `8bf2ce9` plus docs commits; 976 tests pass.
  - Frontend head `e958701`; 152 tests pass; lint, type check, route-guard check and build pass.
  - Nobody has opened the two new pages (`/pending`, `/settings/users`) in a browser yet.
- **Next step:** the rollout, plan Task 12. It was at "stage 1" on 11/16: push both branches, pick a Discord
  channel and copy its id, add `APPROVAL_ALERT_CHANNEL_ID` to the AWS secret `qqqAppsecrets`. Check which of
  those are done before continuing (see "How to check" below).
- **Not started:** Plan 2 (%-only view), Plan 3 (AI cap), Plan 4 (options), then sections B, C, D, G, with E and F
  in between. Each plan is written when the one before it is live.

## Rollout order and the cautions that go with it

The steps are in the plan's Task 12. Reviewers added these, and they matter:

1. Before adding the temporary flag to the server's env file, check the file ends with a newline
   (`sudo tail -c 1 /etc/llm-portfolio/llm.env | xxd`), or the flag gets glued onto the last variable.
2. Apply migration 080 through Supabase's migration tool so it runs in one transaction; a second run must change nothing.
3. The Vercel preview can't be used until the new backend is deployed (the old backend has no `/auth/me`). Do
   the preview checks between the backend merge and the frontend merge.
4. Do the backend merge, the frontend merge and the flag removal in one sitting.
5. After the frontend deploys, Qais's existing login is sent to the sign-in page. He signs in again with Google.
6. If the frontend ever has to be rolled back after the flag is removed, put the flag back first.
7. After rollout: send one real alert to confirm the bot can post in the channel; create the `dev` owner password
   account on the Users page; delete `AUTH_USERS` and `ALLOWED_EMAILS` on Vercel.
8. **No guest or family approvals until Plans 2 and 3 are live.** The API still returns dollar amounts, and guests
   could trigger paid AI work.

## Standing rules (from Qais)

- Commit only when he says go. He pushes and merges, in the browser; nothing is pushed or merged for him unless he asks.
- When a step needs him at a terminal, say which terminal (PowerShell on the PC, or the browser server terminal
  on AWS), where, and which language. He is not a developer; give exact commands and what good output looks like.
- Never loosen the Robinhood read-only guards (`.claude/hooks/robinhood_readonly_guard.py`).
- Never commit `data/security-review-2026-11-10.md` (it contains an exploit recipe; it is gitignored).
- Ask before anything that spends OpenAI money on purpose (re-parsing, re-tagging, backfills).
- Work in `C:\github\dev\...` only. **Never use an old copy of either repo under OneDrive.**

## His decisions (don't re-ask)

- Only qaisme100@gmail.com is owner, plus a `dev` password account.
- Guest and family get the same view: % of portfolio, % P&L, price levels; no dollar amounts, no share counts;
  removed on the server; always the real portfolio.
- Guests see his raw notes unmasked, with exact percentages. He was shown that one note stating a size lets a
  guest work out the portfolio's value, and accepted it.
- Guests and family get 10 AI chats a day each. AI cap starting point: 2,000 calls a day for the pipeline, 500 for the app.
- New sign-ins alert him on Discord. The two old viewer accounts go back to pending.
- Options come out of P&L and trades for everyone; he gets a separate Options tab.

## What is NOT in git and has to be set up per machine

| Thing | Why it matters | What to do on a new machine |
|---|---|---|
| `.env` in the backend repo, and any `.env.local` in `frontend/` | Local settings and keys; never committed | Only needed to run the apps locally. Copy them over by hand through a private channel, or skip: the tests don't need them |
| `.venv` (backend) and `node_modules` (frontend) | Installed packages | `python -m venv .venv` then `.venv\Scripts\python -m pip install -r requirements.txt`; in `frontend/`, `npm ci` |
| `data/` (research files, the security review) | Gitignored on purpose | Copy by hand only if needed. Never commit the security review |
| `~/.ssh/llm-ec2` (SSH key for the server) | Created on the first PC 11/12 | Not required: the browser terminal in the AWS console works from anywhere |
| Claude's chat history and its saved memory | Stored on the PC where the chat ran | This file and the four files above replace them |
| `.superpowers/` (build scratch folder) | Local scratch | Its ledger is copied to `docs/plans/2026-11-13-roles-build-ledger.md` |

## What Claude could reach (checked 11/12)

Supabase project `hlpboklskvnwotsgeetv` (SQL, migrations) and Vercel project `llm-portfolio-frontend`: yes,
through connectors on Qais's Claude account. GitHub: fetch and push over HTTPS only; Qais opens and merges pull
requests. The server and AWS secrets: no; Qais runs those steps. A new session should re-check this before relying on it.

## How to check where the rollout stands

- **Branches pushed?** `git ls-remote --heads origin feat/roles-approval` in each repo prints a line if yes.
- **Merged?** `git fetch origin` then `git log --oneline -1 origin/main` in each repo.
- **Migration 080 applied?** In Supabase: `select version from schema_migrations where version like '080%';`
- **Live site on the new build?** Signed out, open the site: the sign-in page shows the line "New here? Sign in
  with Google, then the owner approves your account."
