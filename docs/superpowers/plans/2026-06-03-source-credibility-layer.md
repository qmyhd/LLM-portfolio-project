# Source Credibility Layer — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Phase 1 Source Credibility Layer — manually-curated S/A/B/C/D person tiers per topic category (with profiles + revision history), context-routed via per-stock topic tags, applied **only** to the Discord-parsed-ideas sentiment source through a dedicated resolver, with full baseline/adjusted/delta explainability.

**Spec:** `docs/superpowers/specs/2026-06-03-source-credibility-layer-design.md` (read it first — this plan implements it verbatim).

**Architecture:** Pure resolver `src/analysis/credibility.py` (math unit-tested without DB; a thin DB-backed loader feeds it) consulted by the sentiment agent. Additive migration `073` (RLS on all). CRUD mirrors `app/routes/profiles.py` (advisory-locked upsert + JSONB revision snapshots + soft archive). Frontend mirrors the Project B Profile/`/profiles` patterns.

**Tech stack:** Python 3.11 · FastAPI · SQLAlchemy 2.0 (`execute_sql` named params) · PostgreSQL/Supabase · Next.js 14 (App Router).

**Conventions (apply to every task):**
- TDD: write the failing test → run it red → implement → run green → commit. Small commits, one concern each.
- DB: `from src.db import execute_sql` (reads) / `transaction()` + `pg_advisory_xact_lock` (writes), named `:param` placeholders only. No SQLite.
- Tests run: `pytest -m "not openai and not integration"`; lint `ruff check`; line-length 120.
- A task that touches code that mirrors an existing file **must open that file and match its structure** (cited per task). Where this plan says "mirror `profiles.py`", reproduce its locking/revision/validation idioms exactly rather than inventing new ones.

**Verification commands (used throughout):**
```
# backend (venv python)
.venv\Scripts\python.exe -m pytest tests/<file> -q --no-header
.venv\Scripts\python.exe -m pytest tests/ -q --no-header -m "not openai and not integration"
.venv\Scripts\ruff.exe check src/ app/ tests/
# frontend
cd ../LLM-portfolio-frontend/frontend ; npm run build
```

---

## Phase A — Pre-implementation verification (`author_id` threading)

> Gate from spec §11. The resolver attributes credibility by **stable Discord `author_id`**, which is **not** on `IdeaData` today (`models.py:37-46` has `author` only). The orchestrator query (`orchestrator.py:184-209`) selects `dm.author` but not `dm.author_id`. Fix the smallest possible path and lock it with a regression test **before** any scoring change.

### Task A1: Add `author_id` to `IdeaData`

**Files:**
- Modify: `src/analysis/models.py:37-46`
- Test: `tests/test_idea_author_threading.py` (create)

- [ ] **Step 1 — failing test:** assert the field exists and defaults safely.

```python
# tests/test_idea_author_threading.py
from src.analysis.models import IdeaData


def test_ideadata_has_author_id_default_empty():
    idea = IdeaData(direction="long", confidence=0.8, labels=[], idea_text="x", created_at="2026-06-01", author="alice")
    assert idea.author_id == ""  # safe neutral default — resolver treats "" as no identity


def test_ideadata_accepts_author_id():
    idea = IdeaData(direction="long", confidence=0.8, labels=[], idea_text="x", created_at="2026-06-01", author="alice", author_id="419660638881579028")
    assert idea.author_id == "419660638881579028"
```

- [ ] **Step 2 — run red:** `pytest tests/test_idea_author_threading.py -q` → FAIL (`author_id` unknown / unexpected kwarg).
- [ ] **Step 3 — implement:** add to `IdeaData` (after `author`):

```python
    author: str
    author_id: str = ""  # stable Discord user id; "" = unattributable (neutral credibility)
```

- [ ] **Step 4 — run green:** `pytest tests/test_idea_author_threading.py -q` → PASS.
- [ ] **Step 5 — commit:** `feat(analysis): add author_id to IdeaData (credibility attribution)`

### Task A2: Carry `dm.author_id` through the orchestrator idea query

**Files:**
- Modify: `src/analysis/orchestrator.py:184-209`
- Test: `tests/test_idea_author_threading.py` (extend)

- [ ] **Step 1 — failing test:** patch `execute_sql` used in the orchestrator's idea assembly to return one row including `author_id`, call the assembly, assert the produced `IdeaData.author_id` is populated. (Mirror the existing orchestrator-test mocking style in `tests/test_analysis_orchestrator.py` — reuse its `monkeypatch`/`AsyncMock` setup. If the idea assembly is inline in the main entrypoint, test via the smallest callable that builds `ideas_list`; otherwise extract a tiny helper `_assemble_ideas(rows) -> list[IdeaData]` and test that.)

```python
def test_orchestrator_threads_author_id(monkeypatch):
    from src.analysis import orchestrator as orch
    row = {"direction": "long", "confidence": 0.9, "labels": [], "idea_text": "buy",
           "created_at": "2026-06-01", "author": "alice", "author_id": 419660638881579028}
    # Assert that an IdeaData built from this row carries author_id as a string.
    ideas = orch._assemble_ideas([type("R", (), {"_mapping": row})()])
    assert ideas[0].author_id == "419660638881579028"
```

- [ ] **Step 2 — run red:** FAIL (no `author_id` in query / not set / helper absent).
- [ ] **Step 3 — implement:**
  - Add `dm.author_id` to the SELECT (line 186-187):
    ```sql
    SELECT dpi.direction, dpi.confidence, dpi.labels, dpi.idea_text,
           dm.created_at, dm.author, dm.author_id
    ```
  - In the `IdeaData(...)` construction (line 201-208) add:
    ```python
                    author=m.get("author", "") or "",
                    author_id=str(m.get("author_id") or ""),
    ```
  - If the test required it, extract the `for row in idea_rows: ideas_list.append(IdeaData(...))` block into a module-level `_assemble_ideas(idea_rows) -> list[IdeaData]` and call it. Keep behavior identical.
- [ ] **Step 4 — run green:** `pytest tests/test_idea_author_threading.py tests/test_analysis_orchestrator.py -q` → PASS.
- [ ] **Step 5 — commit:** `feat(analysis): thread discord author_id into IdeaData via orchestrator`

### Task A3: Confirm `discord_parsed_ideas.author_id` reliability (read-only investigation, no code)

- [ ] Run a read-only check against the live DB (or document if unavailable):
  ```sql
  SELECT count(*) total,
         count(*) FILTER (WHERE dm.author_id IS NOT NULL) AS with_author_id
  FROM discord_parsed_ideas dpi
  LEFT JOIN discord_messages dm ON dpi.message_id::text = dm.message_id
  WHERE dm.created_at > NOW() - INTERVAL '30 days';
  ```
- [ ] Record the coverage % in the PR description. If `author_id` coverage is low, that is **not** a blocker (missing → neutral 1.0 by design), but note it so expectations are set. No code change.

---

## Phase B — Migration 073 (schema)

### Task B1: Write additive migration `073_source_credibility.sql`

**Files:**
- Create: `schema/073_source_credibility.sql`

- [ ] **Step 1 — pre-check (no name collisions):** confirm none of these tables already exist (esp. `people`):
  ```sql
  SELECT tablename FROM pg_tables WHERE schemaname='public'
   AND tablename IN ('people','person_revisions','credibility_categories',
     'person_category_tiers','source_identities','tier_multipliers','stock_topic_tags');
  ```
  Expected: 0 rows. If `people` exists, rename the new table to `credibility_people` throughout this plan and the spec before proceeding (flag to the user first).
- [ ] **Step 2 — author the migration** (additive; mirrors 072 idioms — `IF NOT EXISTS`, `created_at/updated_at TIMESTAMPTZ DEFAULT NOW()`, RLS enable + service-role policy):

```sql
-- schema/073_source_credibility.sql
-- Source Credibility Layer (Phase 1). Additive only. RLS on all new tables.
BEGIN;

CREATE TABLE IF NOT EXISTS public.people (
    id           SERIAL PRIMARY KEY,
    full_name    TEXT NOT NULL,
    display_name TEXT,
    role         TEXT,
    bio          TEXT,
    notes        TEXT,
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.person_revisions (
    id            SERIAL PRIMARY KEY,
    person_id     INTEGER NOT NULL REFERENCES public.people(id) ON DELETE CASCADE,
    snapshot_json JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_person_revisions_person ON public.person_revisions (person_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.credibility_categories (
    slug        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS public.person_category_tiers (
    id            SERIAL PRIMARY KEY,
    person_id     INTEGER NOT NULL REFERENCES public.people(id) ON DELETE CASCADE,
    category_slug TEXT NOT NULL REFERENCES public.credibility_categories(slug),
    tier          CHAR(1) NOT NULL CHECK (tier IN ('S','A','B','C','D')),
    muted         BOOLEAN NOT NULL DEFAULT FALSE,
    rationale     TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (person_id, category_slug)
);

CREATE TABLE IF NOT EXISTS public.source_identities (
    id               SERIAL PRIMARY KEY,
    person_id        INTEGER REFERENCES public.people(id) ON DELETE SET NULL,
    platform         TEXT NOT NULL CHECK (platform IN ('twitter','discord','youtube')),
    platform_user_id TEXT NOT NULL,
    handle           TEXT,
    match_status     TEXT NOT NULL DEFAULT 'suggested'
                       CHECK (match_status IN ('confirmed','suggested','unmatched','conflict')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (platform, platform_user_id)
);
CREATE INDEX IF NOT EXISTS idx_source_identities_person ON public.source_identities (person_id);

CREATE TABLE IF NOT EXISTS public.tier_multipliers (
    tier       CHAR(1) PRIMARY KEY CHECK (tier IN ('S','A','B','C','D')),
    multiplier NUMERIC NOT NULL
);

CREATE TABLE IF NOT EXISTS public.stock_topic_tags (
    id            SERIAL PRIMARY KEY,
    symbol        VARCHAR(20) NOT NULL,
    category_slug TEXT NOT NULL REFERENCES public.credibility_categories(slug),
    weight        NUMERIC NOT NULL CHECK (weight >= 0),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, category_slug)
);
CREATE INDEX IF NOT EXISTS idx_stock_topic_tags_symbol ON public.stock_topic_tags (UPPER(symbol));

-- Seeds -------------------------------------------------------------------
INSERT INTO public.credibility_categories (slug, label, description, sort_order) VALUES
 ('markets',             'Markets',              'Broad market / equity-picking skill',                 10),
 ('company_fundamentals','Company Fundamentals', 'Reading a specific company''s financials/business',   20),
 ('macro',               'Macro',                'Macroeconomics, rates, cycles',                       30),
 ('geopolitics',         'Geopolitics',          'Geopolitics & foreign affairs',                       40),
 ('crypto',              'Crypto',               'Crypto / digital assets',                             50),
 ('options_trading',     'Options Trading',      'Options structure, flow, volatility',                 60),
 ('technical_analysis',  'Technical Analysis',   'Price action / TA',                                   70),
 ('media_noise',         'Media Narratives',     'Skill at interpreting media-driven/noisy narratives', 80)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO public.tier_multipliers (tier, multiplier) VALUES
 ('S',1.35),('A',1.15),('B',1.00),('C',0.75),('D',0.45)
ON CONFLICT (tier) DO NOTHING;

-- RLS (service-role access, matching existing tables) ---------------------
DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['people','person_revisions','credibility_categories',
    'person_category_tiers','source_identities','tier_multipliers','stock_topic_tags']
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', t);
    EXECUTE format($f$CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true);$f$,
                   t || '_service_all', t);
  END LOOP;
END $$;

COMMIT;
```

> Match the **exact RLS policy style used in 072** (open the file). If 072 uses a different role/policy convention than the `DO $$` loop above, replace this block to mirror 072 precisely.

- [ ] **Step 3 — verify locally/staging:** apply via `python scripts/deploy_database.py` against a non-prod target if available, else dry-review. Then `python scripts/verify_database.py --verbose` should show 7 new tables. (Live apply is gated on user approval, like migration 072 was — do NOT apply to prod without explicit OK.)
- [ ] **Step 4 — commit:** `feat(schema): migration 073 source credibility tables + seeds + RLS`

### Task B2: Register expected schema (if the repo tracks it)

**Files:**
- Modify: `src/expected_schemas.py` (only if it enumerates tables/columns used by `verify_database.py`)

- [ ] **Step 1:** check whether `src/expected_schemas.py` lists per-table columns. If yes, add the 7 tables matching the DDL exactly.
- [ ] **Step 2 — verify:** `python scripts/verify_database.py --verbose` passes (or the ASCII-only check from prior sessions, to avoid the Windows charmap emoji crash).
- [ ] **Step 3 — commit:** `chore(schema): register 073 tables in expected_schemas`

---

## Phase C — Resolver (`src/analysis/credibility.py`)

> Split pure math from DB access so the math is exhaustively unit-testable. Implements spec §5 exactly, including the muted hard-exclusion rule.

### Task C1: Pure blend math + types

**Files:**
- Create: `src/analysis/credibility.py`
- Test: `tests/test_credibility_resolver.py` (create)

- [ ] **Step 1 — failing tests** (cover every spec §5 branch):

```python
# tests/test_credibility_resolver.py
import math
from src.analysis.credibility import CredibilityResult, blend_multiplier

MULTS = {"S": 1.35, "A": 1.15, "B": 1.00, "C": 0.75, "D": 0.45}

def _tiers(**kw):  # {category: ("A", muted_bool)}
    return kw

def test_no_tags_is_neutral():
    r = blend_multiplier(tags={}, tiers={}, multipliers=MULTS)
    assert r.multiplier == 1.0 and r.muted_out is False

def test_untiered_category_is_neutral_term():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4}, tiers={}, multipliers=MULTS)
    assert r.multiplier == 1.0

def test_normal_blend():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4},
                         tiers={"markets": ("A", False), "geopolitics": ("S", False)}, multipliers=MULTS)
    assert round(r.multiplier, 4) == 1.23

def test_weights_normalized_at_read_time():
    # unnormalized weights (6/4) give same result as (0.6/0.4)
    r = blend_multiplier(tags={"markets": 6, "geopolitics": 4},
                         tiers={"markets": ("A", False), "geopolitics": ("S", False)}, multipliers=MULTS)
    assert round(r.multiplier, 4) == 1.23

def test_partial_mute_drags_then_clamps():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4},
                         tiers={"markets": ("A", False), "geopolitics": ("S", True)}, multipliers=MULTS)
    assert round(r.multiplier, 4) == 0.69  # (0.6*1.15 + 0.4*0)/1.0, within clamp

def test_partial_mute_clamps_low():
    # markets weight tiny, muted markets + low D geopolitics -> below 0.30 -> clamp 0.30
    r = blend_multiplier(tags={"markets": 0.9, "geopolitics": 0.1},
                         tiers={"markets": ("A", True), "geopolitics": ("D", False)}, multipliers=MULTS)
    # raw = (0.9*0 + 0.1*0.45)/1.0 = 0.045 -> clamp -> 0.30
    assert r.multiplier == 0.30

def test_clamp_high():
    r = blend_multiplier(tags={"markets": 1.0}, tiers={"markets": ("S", False)},
                         multipliers={**MULTS, "S": 2.0})  # 2.0 -> clamp 1.50
    assert r.multiplier == 1.50

def test_fully_muted_is_zero_not_clamped():
    r = blend_multiplier(tags={"markets": 0.6, "geopolitics": 0.4},
                         tiers={"markets": ("A", True), "geopolitics": ("S", True)}, multipliers=MULTS)
    assert r.multiplier == 0.0 and r.muted_out is True
```

- [ ] **Step 2 — run red:** module/functions absent.
- [ ] **Step 3 — implement** the pure core:

```python
# src/analysis/credibility.py
"""Source-credibility resolver. Pure blend math + a DB-backed loader.

Implements docs/superpowers/specs/2026-06-03-source-credibility-layer-design.md §5.
Neutral by default: missing data anywhere resolves to a 1.0 (no-op) multiplier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CLAMP_LO = 0.30
CLAMP_HI = 1.50


@dataclass
class CredibilityResult:
    multiplier: float = 1.0
    muted_out: bool = False                 # True iff every tagged category was muted -> 0.0
    person_id: Optional[int] = None
    person_name: Optional[str] = None
    tiers: dict[str, str] = field(default_factory=dict)   # category -> tier letter (for explainability)


def _clamp(x: float) -> float:
    return max(CLAMP_LO, min(CLAMP_HI, x))


def blend_multiplier(
    *,
    tags: dict[str, float],
    tiers: dict[str, tuple[str, bool]],     # category -> (tier_letter, muted)
    multipliers: dict[str, float],
) -> CredibilityResult:
    """Spec §5 effective multiplier. tags weights are normalized here (read time)."""
    total_w = sum(w for w in tags.values() if w and w > 0)
    if total_w <= 0:
        return CredibilityResult(multiplier=1.0)

    num = 0.0
    used_tiers: dict[str, str] = {}
    for category, w in tags.items():
        if not w or w <= 0:
            continue
        entry = tiers.get(category)
        if entry is None:
            tier_mult = 1.0                  # untiered -> neutral term
        else:
            letter, muted = entry
            used_tiers[category] = letter
            tier_mult = 0.0 if muted else multipliers.get(letter, 1.0)
        num += w * tier_mult

    raw = num / total_w
    if raw == 0.0:                           # ALL tagged categories muted -> hard exclusion
        return CredibilityResult(multiplier=0.0, muted_out=True, tiers=used_tiers)
    return CredibilityResult(multiplier=_clamp(raw), tiers=used_tiers)
```

- [ ] **Step 4 — run green:** `pytest tests/test_credibility_resolver.py -q` → PASS.
- [ ] **Step 5 — commit:** `feat(analysis): credibility blend math (pure, spec §5)`

### Task C2: DB-backed resolver `CredibilityResolver`

**Files:**
- Modify: `src/analysis/credibility.py`
- Test: `tests/test_credibility_resolver.py` (extend, mocking `execute_sql`)

- [ ] **Step 1 — failing test:** patch `src.analysis.credibility.execute_sql` to return canned rows (tier multipliers, this symbol's topic tags, identity→person→tiers for given author_ids); assert `resolver.multiplier(author_id)` returns the right `CredibilityResult`, and an unknown author_id → neutral 1.0 with `person_id is None`.

```python
def test_resolver_unknown_author_is_neutral(monkeypatch):
    import src.analysis.credibility as cred
    monkeypatch.setattr(cred, "execute_sql", lambda *a, **k: [])  # no data anywhere
    r = cred.CredibilityResolver.for_ideas("AAPL", author_ids=["999"])
    res = r.multiplier("999")
    assert res.multiplier == 1.0 and res.person_id is None
```

- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement** `CredibilityResolver`:
  - `@classmethod for_ideas(cls, symbol: str, author_ids: list[str]) -> "CredibilityResolver"` — one batched load:
    - `tier_multipliers` → `{tier: float}` (fallback to spec seeds if table empty).
    - `stock_topic_tags WHERE UPPER(symbol)=:symbol` → `{category_slug: weight}`.
    - `source_identities` (platform='discord', `platform_user_id = ANY(:ids)`, `match_status='confirmed'`) → `{author_id: person_id, person_name}` (join `people`).
    - `person_category_tiers` for those person_ids → `{person_id: {category: (tier, muted)}}`.
  - `.multiplier(author_id: str) -> CredibilityResult`:
    - blank/unknown author_id or no confirmed person → `CredibilityResult(1.0)`.
    - else `res = blend_multiplier(tags=self._tags, tiers=person_tiers, multipliers=self._mults)`, then attach `person_id`/`person_name`.
  - All SQL uses named params; `ANY(:ids)` bound as a list per `db.py` conventions (verify `execute_sql` supports list params; if not, build an `IN (:id0,:id1,...)` clause).
- [ ] **Step 4 — run green.**
- [ ] **Step 5 — commit:** `feat(analysis): DB-backed CredibilityResolver.for_ideas`

---

## Phase D — Sentiment integration (Discord ideas only)

### Task D1: Inject credibility into `_score_discord_ideas`

**Files:**
- Modify: `src/analysis/sentiment.py:51-124` (and its call site in `run`/`score`)
- Test: `tests/test_sentiment_credibility.py` (create)

- [ ] **Step 1 — failing tests:**
  - **Backward-compat:** with a neutral resolver (every `multiplier`=1.0), the discord-ideas signal/confidence/`weighted_score` are **identical** to the current implementation for a fixed idea set, and `metrics["credibility"]["delta"] == 0.0`.
  - **Adjusted differs:** a resolver returning 1.35 for a bullish author vs 1.0 for a bearish author moves `adjusted_score` more bullish than `baseline_score` → `delta > 0`.
  - **Muted drop:** an author whose result is `multiplier==0.0` (muted_out) is excluded from both numerator and denominator (compare to the same set without that idea).
  - **All-muted → no signal:** if every idea's author is muted_out, discord-ideas returns `("neutral", 0.0, ...)` and `metrics["credibility"]["adjusted_score"] == 0.0`.

```python
# tests/test_sentiment_credibility.py
from src.analysis.credibility import CredibilityResult
from src.analysis.models import IdeaData
from src.analysis.sentiment import _score_discord_ideas

def _idea(direction, conf, author_id, created="2026-06-01"):
    return IdeaData(direction=direction, confidence=conf, labels=[], idea_text="x",
                    created_at=created, author="a", author_id=author_id)

class _Resolver:
    def __init__(self, table): self.table = table  # author_id -> CredibilityResult
    def multiplier(self, author_id): return self.table.get(author_id, CredibilityResult(1.0))

def test_neutral_resolver_matches_baseline():
    ideas = [_idea("long", 0.8, "1"), _idea("short", 0.6, "2")]
    sig, conf, m = _score_discord_ideas(ideas, symbol="AAPL", resolver=_Resolver({}))
    assert m["credibility"]["delta"] == 0.0
    assert round(m["credibility"]["adjusted_score"], 4) == round(m["credibility"]["baseline_score"], 4)

def test_muted_author_dropped():
    ideas = [_idea("long", 0.8, "1"), _idea("short", 0.9, "2")]
    res = _Resolver({"2": CredibilityResult(multiplier=0.0, muted_out=True)})
    sig, conf, m = _score_discord_ideas(ideas, symbol="AAPL", resolver=res)
    # only the bullish idea survives -> bullish
    assert sig == "bullish"
```

- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement:** change the signature to
  `_score_discord_ideas(ideas, symbol="", resolver=None)` and keep a single loop with **two accumulators**:
  - `resolver=None` ⇒ treat every multiplier as 1.0 (pure backward-compat path; `credibility.delta==0`).
  - per idea: compute `direction_score`, `confidence`, `time_weight` (unchanged, including the >30d skip). `base_w = confidence * time_weight`. Always accumulate baseline (`base_num += direction_score*base_w; base_den += base_w`). Then `m = resolver.multiplier(idea.author_id).multiplier if resolver else 1.0`; if `m == 0.0`: skip adjusted accumulation (drop); else `adj_num += direction_score*base_w*m; adj_den += base_w*m` and record a contributor `{author_id, person, tiers, effective_mult}` when the result has a `person_id`.
  - `baseline_score = base_num/base_den if base_den else 0.0`; `adjusted_score = adj_num/adj_den if adj_den else 0.0`.
  - The agent's returned `signal`/`confidence` use **adjusted_score** (thresholds unchanged: >0.2 / <-0.2; `confidence=min(abs(adjusted),1)`). If `adj_den==0` → `("neutral", 0.0, ...)`.
  - Extend the metrics dict with:
    ```python
    metrics["credibility"] = {
        "baseline_score": round(baseline_score, 4),
        "adjusted_score": round(adjusted_score, 4),
        "delta": round(adjusted_score - baseline_score, 4),
        "contributors": contributors[:5],   # top by |effect|; or first 5
    }
    ```
  - Keep `weighted_score` = `round(adjusted_score, 4)` so existing readers see the (now credibility-adjusted) score; the baseline is preserved under `credibility`.
- [ ] **Step 4 — run green:** `pytest tests/test_sentiment_credibility.py tests/test_sentiment*.py -q` (run the existing sentiment tests too — they must still pass with `resolver=None`).
- [ ] **Step 5 — commit:** `feat(analysis): credibility-weighted discord-ideas sentiment + explainability`

### Task D2: Build the resolver in the sentiment agent entrypoint

**Files:**
- Modify: `src/analysis/sentiment.py` (the public `run`/`score` that calls `_score_discord_ideas`)
- Test: `tests/test_sentiment_credibility.py` (extend; mock `CredibilityResolver.for_ideas`)

- [ ] **Step 1 — failing test:** patch `CredibilityResolver.for_ideas` to return a stub; assert the agent passes `inp.ticker` + the ideas' `author_id`s and that `metrics["credibility"]` is present on the returned `AnalystSignal`.
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement:** in the sentiment agent's entry, build
  `resolver = CredibilityResolver.for_ideas(inp.ticker, [i.author_id for i in inp.ideas])` and pass it to `_score_discord_ideas(inp.ideas, symbol=inp.ticker, resolver=resolver)`. Wrap the resolver build in try/except → on any failure, log and fall back to `resolver=None` (credibility must **never** break scoring). Do **not** touch `_score_discord_sentiment`, news, or `consensus.py`.
- [ ] **Step 4 — run green:** full analysis suite: `pytest tests/test_analysis_*.py tests/test_sentiment*.py -q`.
- [ ] **Step 5 — commit:** `feat(analysis): sentiment agent builds credibility resolver for its ticker`

---

## Phase E — Backend APIs

> Mirror `app/routes/profiles.py` for the people router (advisory lock keyed off `person_id`, JSONB revision snapshot on every PUT, soft archive via `status`). Two new routers: `people.py` (people + tiers + identities + revisions + unmatched queue) and `credibility.py` (categories, tier-multipliers, stock topic-tags). Register both in `app/main.py` under `Depends(require_api_key)`.

### Task E1: `people` router — core CRUD + tiers + revisions

**Files:**
- Create: `app/routes/people.py`
- Modify: `app/main.py` (register router, prefix `/people`)
- Test: `tests/test_people_api.py` (create; use FastAPI `TestClient`, mock `execute_sql`/`transaction` exactly as `tests/test_profiles_*.py` do — open those first and copy the fixture style)

- [ ] **Step 1 — failing tests:** `POST/PUT /people/{id}` upserts profile+tiers and appends a `person_revisions` snapshot; `GET /people/{id}` returns profile+tiers+identities; `GET /people/{id}/revisions` returns history DESC; `DELETE` sets `status='archived'`; `GET /people` lists with `?category=&tier=&status=` filters and "needs attention" (untiered or has unconfirmed identities) first.
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement** mirroring `profiles.py`: Pydantic `PersonBody` (full_name, display_name, role, bio, notes, tiers: list of `{category_slug, tier, muted, rationale}`); PUT inside `transaction()` with `pg_advisory_xact_lock(:k)` (k hashed from `person_id`; for create, allocate id then lock), upsert `people`, replace `person_category_tiers` for the person, append `person_revisions(snapshot_json = body.model_dump_json())`. Named params throughout.
- [ ] **Step 4 — run green:** `pytest tests/test_people_api.py -q`.
- [ ] **Step 5 — commit:** `feat(api): people router — profile+tiers CRUD with revisions`

### Task E2: `people` router — identities + unmatched review queue

**Files:**
- Modify: `app/routes/people.py`
- Test: `tests/test_people_api.py` (extend)

- [ ] **Step 1 — failing tests:** `POST /people/{id}/identities` links/creates a `source_identities` row (sets `match_status='confirmed'`); inserting a `(platform, platform_user_id)` already linked to another person returns a **409 conflict** and marks/keeps `match_status='conflict'` (never silently reassigns); `DELETE /people/{id}/identities/{sid}` unlinks; `GET /identities/unmatched` returns rows where `match_status IN ('suggested','unmatched','conflict')` plus discord authors seen in `discord_parsed_ideas`/`discord_messages` with no confirmed identity.
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement:** enforce the unique `(platform, platform_user_id)`; on conflict surface it rather than merge (spec §6). The unmatched-queue query LEFT JOINs distinct recent discord authors against `source_identities`.
- [ ] **Step 4 — run green.**
- [ ] **Step 5 — commit:** `feat(api): source-identity linking + unmatched review queue (flag-don't-merge)`

### Task E3: `credibility` router — categories, tier multipliers, stock topic tags

**Files:**
- Create: `app/routes/credibility.py`
- Modify: `app/main.py` (register, prefix `/credibility`; topic-tags path `/stocks/{ticker}/topic-tags` lives here or in `stocks.py` — prefer here to avoid touching `stocks.py`)
- Test: `tests/test_credibility_api.py` (create)

- [ ] **Step 1 — failing tests:** `GET/PUT /credibility/categories` (list + edit label/description/sort_order; additive create allowed); `GET/PUT /credibility/tier-multipliers` (read seeds; update values; reject tiers outside S–D); `GET/PUT /stocks/{ticker}/topic-tags` (read tags for symbol; replace set; weights `>= 0`; advisory lock keyed off `UPPER(symbol)`).
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement** with named params + `transaction()` for writes. Validate `category_slug` exists (FK) and tier letters.
- [ ] **Step 4 — run green:** `pytest tests/test_credibility_api.py -q`.
- [ ] **Step 5 — commit:** `feat(api): credibility config (categories, multipliers, stock topic tags)`

### Task E4: Surface `metrics.credibility` on the analysis response

**Files:**
- Modify: `app/routes/analysis.py` (only if it whitelists/reshapes sentiment `metrics`; if it passes `metrics` through verbatim, no change — add a test asserting passthrough)
- Test: `tests/test_analysis_*` (extend or add)

- [ ] **Step 1 — failing test:** the `/stocks/{ticker}/analysis` payload includes the sentiment agent's `metrics.credibility` (baseline/adjusted/delta/contributors).
- [ ] **Step 2-4:** ensure passthrough (most likely already verbatim); green.
- [ ] **Step 5 — commit:** `test(api): assert credibility breakdown surfaces in analysis payload`

---

## Phase F — Frontend (Next.js, `frontend/src`)

> Mirror Project B's patterns: API route proxies under `app/api/...` using `backendFetch`/`authGuard` (open an existing one, e.g. `app/api/stocks/[ticker]/notes/route.ts`); SWR hooks like `useThesisProfile.ts`; editor components like `ProfilePanel.tsx`; a workspace page like `/profiles`. Verify each task with `npm run build`.

### Task F1: Types + API proxies + hooks

**Files (create):** `frontend/src/types/credibility.ts`; `frontend/src/app/api/people/route.ts`, `app/api/people/[id]/route.ts`, `app/api/people/[id]/revisions/route.ts`, `app/api/people/[id]/identities/route.ts`, `app/api/identities/unmatched/route.ts`, `app/api/credibility/categories/route.ts`, `app/api/credibility/tier-multipliers/route.ts`, `app/api/stocks/[ticker]/topic-tags/route.ts`; `frontend/src/hooks/usePeople.ts`, `useCredibility.ts`.

- [ ] Types mirror the backend Pydantic shapes (Person, PersonTier, SourceIdentity, Category, TierMultiplier, StockTopicTag, CredibilityBreakdown).
- [ ] Each proxy: `await authGuard()`, `backendFetch(...)`, forward method/body, return JSON (copy an existing notes/profile proxy). No business logic in the proxy.
- [ ] Hooks use SWR (the global provider already exists from the loading-UX work).
- [ ] **Verify:** `npm run build` green. **Commit:** `feat(fe): credibility types, api proxies, hooks`

### Task F2: Credibility tab — tier board

**Files (create):** `frontend/src/app/credibility/page.tsx`; `frontend/src/components/credibility/TierBoard.tsx`, `PersonCard.tsx`, `CategorySelect.tsx`. **Modify:** the nav/sidebar to add a "Credibility" entry (find the existing nav component; mirror how `/ideas` or `/profiles` was added).

- [ ] Category selector → rows S/A/B/C/D with the people tiered in that category (PersonCard per person). v1 uses a dropdown to set a person's tier in the selected category (no drag-drop). Empty/neutral states handled.
- [ ] **Verify** `npm run build`. **Commit:** `feat(fe): credibility tab with per-category tier board`

### Task F3: Person profile editor + revision history

**Files (create):** `frontend/src/components/credibility/PersonProfileEditor.tsx`, `RevisionHistory.tsx`, `IdentityLinks.tsx`. (Mirror `ProfilePanel.tsx`.)

- [ ] Identity header (name, role, linked handles + `match_status` badges); per-category tier chips + rationale editor; Save (PUT) → optimistic refresh; revision history list (read-only snapshots).
- [ ] **Verify** `npm run build`. **Commit:** `feat(fe): person profile editor + identities + revision history`

### Task F4: Review queue + stock topic-tags editor + analysis explainability

**Files (create):** `frontend/src/components/credibility/ReviewQueue.tsx`, `StockTopicTagsEditor.tsx`, `frontend/src/components/stock/CredibilityDelta.tsx`. **Modify:** the stock analysis page to render `CredibilityDelta` (reads `metrics.credibility`) and mount `StockTopicTagsEditor` (on the stock page and/or the credibility tab).

- [ ] ReviewQueue lists unmatched/conflict identities with "link to person / create person" actions.
- [ ] `CredibilityDelta`: e.g. *"Sentiment +0.08 from credibility weighting (3 contributors)"* with a tooltip/expand listing contributors; renders nothing when delta is 0 / absent.
- [ ] **Verify** `npm run build`. **Commit:** `feat(fe): review queue, topic-tags editor, analysis credibility delta`

---

## Phase G — Verification & smoke

### Task G1: Full automated verification

- [ ] Backend: `.venv\Scripts\python.exe -m pytest tests/ -q --no-header -m "not openai and not integration"` → all pass.
- [ ] Backend lint: `.venv\Scripts\ruff.exe check src/ app/ tests/` → clean.
- [ ] Frontend: `cd ../LLM-portfolio-frontend/frontend ; npm run build` → compiled successfully.

### Task G2: Manual smoke checklist (against a dev/staging API with migration 073 applied)

- [ ] Create a person (`POST /people`).
- [ ] Link a Discord identity to them (`POST /people/{id}/identities`, platform=discord, real `author_id`).
- [ ] Assign tiers (e.g. markets=A, geopolitics=S).
- [ ] Add stock topic tags (e.g. `LMT = markets 0.6 / geopolitics 0.4`).
- [ ] Run stock sentiment / analysis for that ticker.
- [ ] Confirm a non-zero `credibility.delta` appears in the analysis payload and the UI delta renders.
- [ ] Confirm a Discord author with **no** identity leaves the score **unchanged** (delta 0 for their ideas).
- [ ] Confirm a **muted** source has **zero** effect (idea dropped; verify against the same run without the mute).

### Task G3: Finish the branch

- [ ] Use **superpowers:finishing-a-development-branch** (verify tests → push + open PR for backend; repeat for frontend). Note migration 073 must be applied to the live DB (gated on user OK) before the analysis endpoints reflect credibility in prod.

---

## Self-review notes (author)

- **Spec coverage:** A (author_id gate §11) · B (data model §4 + seeds §2) · C (resolver §5 incl. muted §5) · D (sentiment integration + explainability §5/§7) · E (API §8) · F (UI §9) · G (guardrails §12 via smoke). ✔
- **Type consistency:** `CredibilityResult.multiplier`/`muted_out`/`person_id`/`tiers` used identically in C1, C2, D1. `blend_multiplier` signature stable across tests + impl. ✔
- **No silent behavior change:** D1 keeps `resolver=None` byte-for-byte equal to today; existing sentiment tests must pass unchanged. ✔
- **Known mechanical tasks (E, F):** specified by mirroring named template files rather than reproducing every line; each cites its template and has explicit test/verify/commit steps. Acknowledged tradeoff for a feature this size.
