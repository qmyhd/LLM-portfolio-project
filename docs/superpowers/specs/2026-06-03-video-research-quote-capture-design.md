# Video Research / Quote Capture — Design Spec

**Status:** Draft for review (2026-06-03)
**Goal:** A standalone workspace where you paste a YouTube URL, watch the video alongside its synced transcript, select transcript spans, and save them as **quotes** — each linked to a speaker (Person), a bucket (credibility category), and optionally a ticker, a stock thesis, a freeform thesis note, tags, and notes. A clean, auditable, personal research library.

**Architecture:** New backend router (`app/routes/videos.py`) that (a) resolves a YouTube URL → metadata + caption transcript on demand via `youtube-transcript-api` + oEmbed (no API key), and (b) CRUDs saved quotes in a new additive migration `074`. Speaker attribution **reuses** the credibility `source_identities` + unmatched-review-queue machinery (flag-don't-merge). New Next.js `/research` workspace: embedded IFrame player + synced transcript + quote-capture drawer + quote library. **Transcripts are never persisted** — only saved quote excerpts are stored.

**Tech stack:** Python 3.11 · FastAPI · `youtube-transcript-api` (new dep) · SQLAlchemy 2.0 · PostgreSQL/Supabase · Next.js 14 (App Router) · YouTube IFrame Player API.

---

## 1. Current-state findings (design reuses, not reinvents)

- **No YouTube/transcript/ASR dependency exists** — transcript fetching is net-new (add `youtube-transcript-api`).
- **`source_identities` already supports `platform='youtube'`** (migration 073) — a channel can map to a tiered **Person**, and unmatched/suggested identities already surface via `GET /identities/unmatched` (flag-don't-merge). This feature reuses that directly.
- **`credibility_categories`** (geopolitics, markets, macro, crypto, options_trading, technical_analysis, company_fundamentals, media_noise) are the quote **buckets**.
- **`stock_thesis_profiles`** (072, per-(symbol,bucket)) is the optional **stock-thesis** link target.
- There is an unrelated FMP earnings-transcript helper (`openbb_service.get_earnings_transcript`) — not used here (that's FMP calls, not YouTube).
- Latest migration is `073`; this feature is `074`.

---

## 2. Locked decisions (from shaping)

1. **Standalone feature** — a "Video Research / Quote Capture" workspace; not bolted onto an existing page.
2. **YouTube URL input** (user-pasted) in V1.
3. **Captions-only transcript** — try official/available captions; if none, mark **unavailable** (no ASR/Whisper, no video download, no bypassing private/disabled captions in V1).
4. **Buckets = the 8 credibility categories + free-form tags.**
5. **All associations optional, all at once** — a quote may carry any combination of speaker, bucket, ticker, stock-thesis, thesis-note, tags, notes; none required (frictionless capture).
6. **Transcript storage = saved excerpts only** — the full transcript is fetched live each watch session and **never persisted**; only saved quotes are stored.
7. **Speaker linking = auto-if-confirmed, else review** — reuse `source_identities`; a not-yet-confirmed channel is upserted as a `suggested` identity so it appears in the existing review queue.
8. **Forward-compatible, no scoring in V1** — schema shaped (speaker→person, bucket→category, ticker, timestamp) so quotes *could* feed credibility/sentiment later; no scoring logic now.
9. **Private, single-user, existing Supabase + RLS** — same storage/security posture as all current data.
10. **Per-quote speaker** — a quote's speaker defaults to the video's resolved channel-Person but is overridable per quote (handles interviews — e.g. Tucker/Piers interviewing a guest — without diarization).

---

## 3. Concepts

- **Video** — identified by its parsed YouTube `video_id`; metadata (title, channel name/url) fetched live via oEmbed. Not a stored entity beyond what's denormalized onto saved quotes.
- **Transcript segment** — `{ text, start, duration }` from `youtube-transcript-api`, shown live; the unit you select to quote. Never persisted.
- **Quote** — a saved excerpt: text + `[start, end]` timestamp + source video + optional associations. The only persisted artifact.
- **Speaker** — a `Person` (credibility feature). Resolved from the channel via a confirmed YouTube `source_identity`; overridable per quote.
- **Bucket** — a `credibility_categories.slug`. Plus free-form `tags`.

---

## 4. Data model — migration `074` (additive only, RLS on)

One table (denormalized video fields — keeps each quote self-contained and auditable, matching "saved excerpts only"; a normalized `video_sources` table is a possible later refinement).

| Column | Type | Notes |
|---|---|---|
| `id` | SERIAL PK | |
| `video_id` | TEXT NOT NULL | parsed YouTube id (grouping key) |
| `video_url` | TEXT NOT NULL | original pasted URL |
| `video_title` | TEXT | from oEmbed |
| `channel_name` | TEXT | from oEmbed `author_name` |
| `channel_url` | TEXT | from oEmbed `author_url` (channel key for identity) |
| `quote_text` | TEXT NOT NULL | the saved excerpt (editable at save) |
| `start_seconds` | NUMERIC NOT NULL | quote start timestamp |
| `end_seconds` | NUMERIC | optional end timestamp |
| `person_id` | INTEGER FK→people ON DELETE SET NULL | speaker (optional, per-quote) |
| `category_slug` | TEXT FK→credibility_categories | bucket (optional) |
| `ticker` | VARCHAR(20) | optional |
| `stock_thesis_profile_id` | INTEGER FK→stock_thesis_profiles ON DELETE SET NULL | optional stock-thesis link |
| `thesis_note` | TEXT | optional freeform geopolitical/investment thesis note |
| `tags` | TEXT[] NOT NULL DEFAULT '{}' | free-form tags |
| `notes` | TEXT | user notes |
| `status` | text NOT NULL DEFAULT 'active' CHECK in (active, archived) | soft archive |
| `saved_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | |
| `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT NOW() | trigger-maintained |

Indexes: `(video_id)`, `(person_id)`, `(category_slug)`, `(UPPER(ticker))`. RLS **enabled** (no policy — service role, mirrors 073). `updated_at` trigger reuses 073's `tg_credibility_set_updated_at()`. Records its `schema_migrations` ledger row + `expected_schemas.py` entry.

> **No transcript table.** Per decision 6, transcripts are fetched live and never stored.

---

## 5. Transcript & metadata ingestion (live, on demand)

`youtube-transcript-api` fetches caption tracks (timed text) without an API key; oEmbed (`https://www.youtube.com/oembed?url=…&format=json`) gives `title`, `author_name`, `author_url` without an API key. Both are best-effort and fail-safe.

**Approaches considered:**
- **(A) `youtube-transcript-api` server-side** *(chosen)* — returns timestamped segments, no key, no video download.
- **(B) YouTube Data API `captions.download`** — requires OAuth **and** video ownership; unusable for arbitrary videos.
- **(C) client-side fetch** — CORS-blocked; also exposes scraping from the browser.

**Flow** (`POST /videos/resolve`, body `{ url }`):
1. Parse `video_id` from the URL (`v=`, `youtu.be/…`, `/shorts/…`, `/embed/…`); 400 on unparseable.
2. oEmbed → `title`, `channel_name`, `channel_url` (best-effort; nulls on failure).
3. `youtube-transcript-api` → `segments: [{text, start, duration}]`. On *no captions / disabled / unavailable* → `transcriptAvailable: false, segments: [], reason`.
4. **Speaker resolution:** derive a stable channel key from `channel_url` (the `@handle` or `/channel/UC…` id). Look up `source_identities(platform='youtube', platform_user_id=key, match_status='confirmed')` → `suggestedPersonId/Name`. If none, **upsert** a `source_identities` row (`platform='youtube'`, `platform_user_id=key`, `handle=channel_name`, `match_status='suggested'`, `person_id=NULL`) so the channel appears in `GET /identities/unmatched` for later linking. (Never auto-creates a Person; never merges.)
5. Return `{ videoId, url, title, channelName, channelUrl, transcriptAvailable, segments, reason?, suggestedPersonId, suggestedPersonName }`.

All external calls wrapped in `@hardened_retry` and try/except — a fetch failure returns `transcriptAvailable:false` with a reason, never a 500. **Known risk:** `youtube-transcript-api` can be rate-limited/blocked from datacenter IPs (EC2) and can break on YouTube changes; acceptable for personal V1 (degrades to "unavailable"). Mitigation (proxy / caching) deferred.

---

## 6. API (new router `app/routes/videos.py`, root-mounted, `Depends(require_api_key)`)

```
POST   /videos/resolve              {url} -> metadata + live transcript segments + suggested speaker
GET    /quotes                      list; filters ?person_id= &category= &ticker= &video_id= &status= &q=(text search)
POST   /quotes                      create a quote (all fields; resolves nothing it isn't given)
GET    /quotes/{id}                 detail (+ joined person/category labels)
PUT    /quotes/{id}                 update (re-bucket, edit associations/notes)
DELETE /quotes/{id}                 soft archive (status='archived')
```

`POST /quotes` body: `{ videoId, videoUrl, videoTitle, channelName, channelUrl, quoteText, startSeconds, endSeconds?, personId?, categorySlug?, ticker?, stockThesisProfileId?, thesisNote?, tags?, notes? }`. Named `:param` placeholders; writes via `transaction()` (advisory lock keyed off `video_id` is optional here — quotes are append-only, low contention). `GET /quotes` LEFT JOINs `people` + `credibility_categories` for display labels. List defaults to `status='active'`.

---

## 7. UI — `/research` workspace (text wireframe; browser companion deferred)

```
┌ Video Research ─────────────────────────────────────────────────────────┐
│ [ Paste YouTube URL ............................ ] [Load]   [Library ▸]  │
├──────────────────────────────────┬──────────────────────────────────────┤
│                                  │  Transcript            as of HH:MM    │
│      ▶ embedded YouTube           │  ──────────────────────────────────  │
│        (IFrame player)            │  00:12  ……………… (current line ◀ hi-lit)│
│                                  │  00:18  ……………… ← click seeks player   │
│   [Tucker — @TuckerCarlson]       │  00:25  ……………… [▒ selected span ▒]    │
│   speaker: Tucker (suggested)     │  …                                    │
│                                  │  [ Save selection as quote ]          │
└──────────────────────────────────┴──────────────────────────────────────┘
```

- **Load:** `POST /videos/resolve` → embed `https://www.youtube.com/embed/{videoId}` via the **IFrame Player API**; render `segments` as a scrollable transcript. If `transcriptAvailable:false` → show the video + a clear "No transcript available for this video" banner (capture disabled).
- **Sync:** poll `player.getCurrentTime()` (~250ms while playing) → highlight + auto-scroll the segment whose `[start, start+duration]` contains the time. Click a segment → `player.seekTo(start)`. (Graceful degradation: if the player API fails to init, the transcript still renders as a clickable list with no live highlight.)
- **Select → Save:** select one or more contiguous segments → a **capture drawer** opens prefilled with the joined quote text (editable), `startSeconds` = first segment start, `endSeconds` = last segment end, and **speaker prefilled** from `suggestedPerson`. Fields: bucket (category select), speaker (person select + "create person"), ticker (optional), stock thesis (optional — pick from existing profiles for the ticker), thesis note (textarea), tags, notes. Save → `POST /quotes`.
- **Quote library** (`/research/library` or a tab): filterable list/grid (by bucket, person, ticker, video, text search). Each card: quote text, speaker, bucket chip, tags, the source video link **deep-linked to the timestamp** (`…&t={start}s`), notes; edit / archive actions.
- **Nav:** add a "Research" (or "Quotes") entry to the sidebar `researchNav`.

---

## 8. Forward-compatibility (no V1 scoring)

The quote schema intentionally carries `person_id`, `category_slug`, `ticker`, and timestamps. A later phase could treat a saved quote as a person-attributable signal (e.g. weight it by the speaker's tier in the quote's category — exactly the credibility resolver's inputs) and feed sentiment/credibility. **No such logic in V1.**

---

## 9. Out of scope for V1

Whisper/ASR fallback · whole-video auto-summarization · multi-speaker diarization · automatic credibility scoring from YouTube · browser extension · mobile-first polish · bulk/channel ingestion · bypassing unavailable/private captions · video download · a normalized `video_sources` table · quote export (privacy choice was plain private storage).

---

## 10. Guardrails / risks

- **`youtube-transcript-api` fragility** — may be blocked from EC2/datacenter IPs or break on YouTube changes; always degrades to `transcriptAvailable:false` (never crashes). Flagged for the user; proxy/caching mitigation deferred.
- **Fail-safe ingestion** — every external call is retry-wrapped + try/except; `/videos/resolve` never 500s on a fetch miss.
- **Flag-don't-merge** preserved — YouTube channels resolve to a Person only via a *confirmed* identity; otherwise `suggested` (review queue), never auto-merged or auto-Person-created.
- **Additive 074, RLS on**, no existing-table changes; private single-user storage.
- **No transcript persistence** — only user-selected excerpts (personal fair-use notes) are stored.

---

## 11. Open questions for review

1. Workspace route name — **`/research`** vs `/videos` vs `/quotes`? (spec assumes `/research`.)
2. Quote library as a separate page vs a tab within `/research`? (spec assumes a tab/section.)
3. Is denormalized single-table acceptable for V1, or do you want the normalized `video_sources` table now (cleaner per-video grouping, slightly more build)?
