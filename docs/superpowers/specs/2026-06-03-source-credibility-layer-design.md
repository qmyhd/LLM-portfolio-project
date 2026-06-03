# Source Credibility Layer — Design Spec

**Status:** Approved for planning (2026-06-03)
**Goal:** Add a manually-curated person/source credibility layer — S/A/B/C/D tiers per topic category, with profiles and revision history — that plugs into the existing sentiment scoring so a source's track record deterministically and *explainably* weights how much their opinion moves the score.

**Architecture:** A dedicated, pure, unit-testable resolver module (`src/analysis/credibility.py`) is consulted live by the sentiment agent. New data lives in additive migration `073` (RLS on all tables). Mirrors Project B's profile pattern: main table + JSONB revision snapshots + advisory-locked upserts.

**Tech stack:** Python 3.11 · FastAPI · SQLAlchemy 2.0 (`execute_sql` named params) · PostgreSQL/Supabase · Next.js 14 frontend.

---

## 1. Current-state findings (design is grounded on these)

- **Sentiment scoring** (`src/analysis/sentiment.py`) blends three sources with fixed weights: Discord parsed ideas (0.50), a Discord sentiment proxy (0.20), and news keywords (0.30). Each contribution is already multiplied by its confidence — that multiplication is the natural insertion point for a credibility weight.
- **Only Discord parsed ideas are person-attributable today.** News is keyword-based. Twitter is ingested into `twitter_data` but **nothing in `src/analysis/` reads it** — Twitter does not reach the scoring model at all, and `twitter_data.author_id` is currently **not persisted**.
- **Authorship is captured**: `discord_messages.author` / `author_id`, `discord_parsed_ideas.author_id`. No per-person/per-account metadata exists anywhere yet.
- **Consensus** (`src/analysis/consensus.py`) weights five agents (sentiment = 0.15). This is **not** changed by this feature.
- **Project B profile pattern** (migration 072, `app/routes/profiles.py`): main table + `*_revisions` snapshot table + `pg_advisory_xact_lock` upserts + soft-delete via `status`. This feature mirrors it. Latest migration is `072`; this feature is `073`.

---

## 2. Locked decisions

1. **Approach A** — dedicated `src/analysis/credibility.py` resolver consulted live by the sentiment agent (no precomputed cache; no inlining into `sentiment.py`).
2. Migration **073 is additive only**, **RLS on all new tables**; no existing-table schema changes in v1.
3. **Manual tiering only in v1** — no automated credibility inference.
4. Mirror Project B: **main table + revision snapshots + advisory-locked upserts**.
5. **Stable source identities** keyed on `(platform, platform_user_id)`, never on display names.
6. **Flag-don't-merge** for uncertain/conflicting identities.
7. **v1 applies credibility only to Discord parsed ideas.** Not Twitter, not news.
8. **Explainability preserved**: every scored result exposes baseline score, credibility-adjusted score, delta, and top contributors.
9. **Pre-implementation gate**: confirm `author_id` is actually threaded through `IdeaData` / the orchestrator's idea assembly before wiring scoring (see §11).
10. **Context-routed** credibility via **per-stock topic tags**; effective multiplier = weighted blend of the author's category tiers across the stock's tags.

### Tunable parameters (v1 seeds)

| Parameter | Value |
|---|---|
| Tier multipliers | **S=1.35, A=1.15, B=1.00, C=0.75, D=0.45** |
| Muted (person muted in a category) | **0.00 — true hard exclusion; bypasses the clamp and drops the idea from the average (see §5)** |
| Effective-multiplier clamp | **[0.30, 1.50]** — applied only to **nonzero** blended values |
| Untiered category term | **1.00** (neutral) |
| Stock with no topic tags | **1.00** (neutral, no change) |
| Author with no confirmed identity | **1.00** (neutral) |

### Initial categories (`credibility_categories` seed)

`markets`, `company_fundamentals`, `macro`, `geopolitics`, `crypto`, `options_trading`, `technical_analysis`, `media_noise`

> **Tier direction is uniform across every category: a higher tier always means *more* credible/trusted, never less.** `media_noise` means **skill at interpreting media-driven / noisy narratives** (separating signal from hype) — an S there is someone who reads noisy coverage well, not someone who *is* noise. To down-weight a low-signal pundit, tier them **C/D or muted** in the relevant categories; never invert the scale.

---

## 3. Concepts & vocabulary

- **Person** — a curated entity (e.g. Mearsheimer, Sachs, a Twitter trader, a Discord member). Has a narrative profile + revision history.
- **Source identity** — a stable platform handle mapping to a person: `(platform, platform_user_id)`. One person → many identities. Keyed on the numeric/stable ID, not the display name.
- **Category** — a credibility dimension (see initial list). Editable taxonomy.
- **Tier** — `S/A/B/C/D` per `(person, category)`, plus a `muted` flag. Maps to a numeric multiplier.
- **Stock topic tags** — per-stock weighted category relevance (e.g. `LMT = markets 0.6 / geopolitics 0.4`). The routing input; **normalized at read time**.

---

## 4. Data model — migration `073` (additive only, RLS on all)

| Table | Key columns | Purpose |
|---|---|---|
| `people` | `id PK`, `full_name`, `display_name`, `role`, `bio`, `notes`, `status` (active/archived, default active), `created_at`, `updated_at` | Person + narrative profile. |
| `person_revisions` | `id PK`, `person_id FK→people ON DELETE CASCADE`, `snapshot_json JSONB`, `created_at` | Full snapshot (profile + all tiers + identity links) per save. Indexed `(person_id, created_at DESC)`. |
| `credibility_categories` | `slug TEXT PK`, `label TEXT`, `description TEXT`, `sort_order INT` | Editable taxonomy. Seeded with the 8 initial categories. |
| `person_category_tiers` | `id PK`, `person_id FK`, `category_slug FK→credibility_categories`, `tier CHAR(1)` CHECK in (S,A,B,C,D), `muted BOOL default false`, `rationale TEXT`, `updated_at`, **UNIQUE(person_id, category_slug)** | Core tier data. |
| `source_identities` | `id PK`, `person_id FK NULL`, `platform TEXT` CHECK in (twitter,discord,youtube), `platform_user_id TEXT`, `handle TEXT`, `match_status TEXT` CHECK in (confirmed,suggested,unmatched,conflict) default 'suggested', `created_at`, `updated_at`, **UNIQUE(platform, platform_user_id)** | Stable identity + flag-don't-merge. |
| `tier_multipliers` | `tier CHAR(1) PK`, `multiplier NUMERIC NOT NULL` | Tunable curve. Seeded S=1.35, A=1.15, B=1.00, C=0.75, D=0.45. (`muted` ⇒ 0.00, handled in resolver.) |
| `stock_topic_tags` | `id PK`, `symbol VARCHAR(20)`, `category_slug FK`, `weight NUMERIC` CHECK (weight >= 0), `updated_at`, **UNIQUE(symbol, category_slug)** | Per-stock routing. Weights normalized at read time. |

Seven tables; three (`credibility_categories`, `tier_multipliers`, `stock_topic_tags`) are small config/seed. All get RLS enabled (service-role access), consistent with the existing schema.

---

## 5. Scoring logic

**Key property:** credibility is a **weight on the average**, not a scale on the score. It changes *which* ideas dominate the Discord-ideas sub-score; it never pushes the result outside `[-1, 1]`, and it **reduces exactly to today's behavior when every multiplier is 1.0** (backward-compatible by default).

### Effective multiplier for a Discord idea about stock `X` by person `P`

```
tags(X)        = { category: weight, ... }      # from stock_topic_tags, raw (weight >= 0)
tier_mult(P,c) = 0.00                               if P is MUTED in c       (hard exclusion)
               = tier_multipliers[ P.tier_in(c) ]   if P is tiered in c
               = 1.00                               if P is untiered in c    (neutral)

# normalize tag weights at read time; muted categories stay in the denominator
W   = Σ_c tags(X)[c]                                 # all tagged categories, muted included
raw = ( Σ_c tags(X)[c] × tier_mult(P,c) ) / W        if W > 0
    = 1.00                                            if W == 0   (stock has no tags → neutral)

effective_mult = 0.00                  if raw == 0.0   (ALL relevant categories muted — NOT clamped)
               = clamp(raw, 0.30, 1.50) otherwise
```

**Muted is a true hard exclusion.** A muted `(person, category)` contributes `0.00` to the numerator while its tag weight stays in `W`, so a *partial* mute drags the blend down but is still clamped to `[0.30, 1.50]`; only when **every** tagged category for that person+symbol is muted does `raw` hit `0.0`, and that `0.00` is preserved (never clamped up to `0.30`).

**Worked examples** (`LMT = markets 0.6 / geopolitics 0.4`):

- Normal — P = markets:A(1.15), geopolitics:S(1.35): `(0.6×1.15 + 0.4×1.35)/1.0 = 1.23`.
- Partial mute — P = markets:A(1.15), geopolitics:muted: `(0.6×1.15 + 0.4×0)/1.0 = 0.69` → clamp → `0.69`.
- Fully muted — P muted in both: `0.00` (preserved, not clamped).

**Safe defaults:** no tags on the stock → `1.00`; author has no confirmed identity/person → `1.00`; person untiered in a tagged category → that term is `1.00`.

### Application in `sentiment.py` (Discord-ideas source only)

`effective_mult` is an additional weight factor alongside `confidence` and `time_weight`, with a hard-exclusion drop for fully-muted sources:

```
for each Discord idea by person P about stock X:
    m = effective_mult(P, X)
    if m == 0.00:                  # fully-muted source → excluded entirely
        continue                   #   contributes to NEITHER numerator nor denominator
    num   += direction_score × confidence × time_weight × m
    denom += confidence × time_weight × m

if denom == 0:                     # no surviving ideas (e.g. every author muted)
    discord_ideas → confidence 0 / neutral   # no signal; contributes nothing to overall sentiment
else:
    discord_ideas_score = num / denom        # ∈ [-1, 1]
```

The Discord **sentiment proxy** (0.20) and **news** (0.30) sources are **untouched** in v1. The agent-level weights in `consensus.py` are **not** changed.

---

## 6. Identity & matching (flag-don't-merge)

- **At scoring time:** resolve `discord author_id` → `source_identities(platform='discord', platform_user_id=author_id, match_status='confirmed')` → `person_id` → tiers. No confirmed match ⇒ neutral `1.00` (no effect).
- **Review queue:** Discord authors appearing in `discord_parsed_ideas` with no confirmed identity are surfaced as `suggested`/`unmatched` rows. The user links them to an existing person or creates one.
- **Conflicts:** anything that would force two people onto the same `(platform, platform_user_id)` is marked `conflict` and surfaced — **never auto-merged**.
- **Twitter & YouTube identities** can be recorded now (the table supports them), but Twitter does **not** affect scoring until Phase 2 (see §10), and `twitter_data.author_id` must be persisted first.

---

## 7. Explainability

The sentiment agent computes its Discord-ideas sub-score **twice** — once with all multipliers forced to `1.0` (baseline), once with real multipliers — and records in `AnalystSignal.metrics`:

```jsonc
"credibility": {
  "baseline_score":  0.42,        // discord-ideas sub-score with all mults = 1.0
  "adjusted_score":  0.50,        // with real credibility multipliers
  "delta":           0.08,        // adjusted − baseline, on the -1..1 scale
  "contributors": [
    { "person": "…", "author_id": "…", "symbol": "LMT",
      "tiers": { "markets": "A", "geopolitics": "S" },
      "effective_mult": 1.23 }
    // … top contributors by |contribution change|
  ]
}
```

Surfaced on the stock analysis page, e.g. *"Sentiment +0.08 from credibility weighting (3 contributors)."*

---

## 8. API (mirrors `app/routes/profiles.py`: advisory-locked upsert + snapshot revision)

```
GET    /people                        list; filters (category, tier, status); "needs attention" first
GET    /people/{id}                   profile + tiers + identities + revisions
PUT    /people/{id}                   upsert profile+tiers (advisory lock on person_id) + append revision
DELETE /people/{id}                   soft archive (status='archived')
GET    /people/{id}/revisions         history (DESC, limit 100)
POST   /people/{id}/identities        link a source identity / confirm a suggestion
DELETE /people/{id}/identities/{sid}  unlink
GET    /identities/unmatched          review queue (suggested/unmatched/conflict)
GET/PUT /credibility/categories       manage taxonomy
GET/PUT /credibility/tier-multipliers tune the curve
GET/PUT /stocks/{ticker}/topic-tags   per-stock routing tags
```

All DB access uses named `:param` placeholders; writes use `transaction()` + `pg_advisory_xact_lock` with a key hashed from `person_id` (people writes) / `(symbol)` (topic-tag writes).

---

## 9. UI — new **Credibility** tab (text wireframe; visual mockups deferred)

```
┌ Credibility ───────────────────────────────────────────────┐
│ [Category ▼ markets]   [+ Add person]   [Review queue (4)]  │
│                                                             │
│  S  │ [Sachs]  [Prof Jiang]                                 │
│  A  │ [Mearsheimer]  [@trader_x]                            │
│  B  │ [Piers Morgan]                                        │
│  C  │ [Tucker Carlson]                                      │
│  D  │ [@pump_acct]                                          │
└─────────────────────────────────────────────────────────────┘
```

- **Person profile page:** identity header (name, role, linked handles + match-status badges) · per-category tier chips + rationale · revision history · (Phase 3) curated quotes/YouTube.
- **Review queue:** unmatched/conflict identities to link or create.
- **Stock topic-tags editor:** small panel (on the stock page and/or in this tab).
- v1 sets tiers via a per-category dropdown; drag-to-re-tier is a later nicety.

---

## 10. Phasing

- **Phase 1 (this build):** migration 073 · people/tiers/identities/categories/topic-tags CRUD + revisions · review queue · `credibility.py` resolver · wire into the Discord-ideas sentiment source with explainable delta · Credibility tab + topic-tag editor + analysis-page explainability.
- **Phase 2:** persist `twitter_data.author_id` (small ingestion fix) · make Twitter a person-attributable sentiment source and apply credibility there · auto-suggest identity matches and stock topic tags.
- **Phase 3:** YouTube transcript source — curated videos/playlists → transcript pull → quote extraction → attach to person profiles, feed thesis info.

**Explicitly out of scope for v1:** Twitter credibility (blocked on `author_id` persistence), news credibility, any automated credibility/topic inference, drag-and-drop tiering, the YouTube source.

---

## 11. Pre-implementation verification (must confirm before wiring §5)

- **`author_id` threading:** the sentiment agent consumes ideas via `IdeaData` assembled by the orchestrator. Confirm `author_id` reaches the agent. If not, extend the orchestrator's idea query (it already joins `discord_messages`) to carry `discord_messages.author_id` into `IdeaData`. The resolver cannot attribute credibility without it.
- Confirm `discord_parsed_ideas.author_id` is reliably populated for the channels that feed scoring (it is the join key for identity resolution).

---

## 12. Guardrails

- Credibility-weighted **average** ⇒ result stays in `[-1, 1]`; **identical to today** when all tiers neutral/absent → safe rollout.
- Nonzero blended multiplier clamped to **[0.30, 1.50]**; a fully-muted source resolves to **0.00** and is dropped from the average entirely (not clamped up).
- Fully manual, auditable, revisioned; the explainability delta is **computed** (baseline vs adjusted), never asserted.
- 073 additive only; RLS on all new tables; no existing-table changes in v1.
- Twitter scoring stays off until `author_id` is persisted; news scoring untouched.
