# Video Research / Quote Capture — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) tracking.

**Goal:** Ship V1 of the Video Research / Quote Capture workspace — paste a YouTube URL, watch it alongside a live synced caption transcript, select spans, and save quotes (speaker/Person, bucket/category, optional ticker/stock-thesis/thesis-note/tags/notes) into a filterable library at `/research`.

**Spec:** `docs/superpowers/specs/2026-06-03-video-research-quote-capture-design.md` (implements it verbatim).

**Architecture:** New `src/youtube.py` (pure URL/channel parsing + fail-safe transcript/oEmbed fetch) → new `app/routes/videos.py` (`POST /videos/resolve` + quotes CRUD) → additive migration `074` (`video_quotes`, RLS on) → Next.js `/research` workspace (IFrame player synced to a clickable transcript → capture drawer → library tab). Speaker attribution reuses credibility `source_identities` + the unmatched review queue. Transcripts are fetched live, never persisted.

**Tech stack:** Python 3.11 · FastAPI · `youtube-transcript-api` (new) · `requests` · SQLAlchemy 2.0 · PostgreSQL/Supabase · Next.js 14 · YouTube IFrame Player API.

**Conventions (every task):**
- TDD: failing test → red → implement → green → commit. One concern per commit. Small commits.
- DB: `execute_sql` (reads) / `transaction()` (writes), named `:param` only. No SQLite.
- Mirror existing files where cited (open them first): `app/routes/people.py` (CRUD/router idioms), `tests/test_people_api.py` (TestClient + `DISABLE_AUTH` + `_row` + `@patch(...execute_sql/transaction)`), `schema/073_source_credibility.sql` (migration idioms), `app/credibility` frontend (page/hook/proxy patterns).
- **Never** commit `.claude/settings.local.json`. Stage only named files per commit (`git add <path>` — never `-A/./-u`).
- **Migration 074 must NOT be applied to the live DB without explicit owner approval** (Phase G gate).
- Commit footer (last line): `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

**Branches:** `feature/video-research` off latest `main` in BOTH repos (create at the start of Phase A backend / Phase E frontend).

**Verification commands:**
```
.venv\Scripts\python.exe -m pytest tests/<file> -q --no-header
.venv\Scripts\python.exe -m pytest tests/ -q --no-header -m "not openai and not integration"
.venv\Scripts\ruff.exe check src/ app/ tests/
# frontend (from ../LLM-portfolio-frontend/frontend)
npm run build
```

---

## Phase A — Transcript spike + URL/channel parser

### Task A1: Dependency + pure URL/channel parsers

**Files:** `requirements.txt` (modify), `src/youtube.py` (create), `tests/test_youtube.py` (create)

- [ ] **Step 1 — failing tests** (pure, no network):
```python
# tests/test_youtube.py
from src.youtube import parse_video_id, parse_channel_key


def test_parse_video_id_watch():
    assert parse_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

def test_parse_video_id_short():
    assert parse_video_id("https://youtu.be/dQw4w9WgXcQ?t=30") == "dQw4w9WgXcQ"

def test_parse_video_id_shorts_embed_live():
    assert parse_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_video_id("https://www.youtube.com/live/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

def test_parse_video_id_invalid():
    assert parse_video_id("https://example.com/foo") is None
    assert parse_video_id("not a url") is None

def test_parse_channel_key_prefers_channel_id():
    # stable UC id preferred
    assert parse_channel_key("https://www.youtube.com/channel/UCabc123DEF456ghiJKL789m") == "UCabc123DEF456ghiJKL789m"

def test_parse_channel_key_handle_best_effort():
    assert parse_channel_key("https://www.youtube.com/@PiersMorganUncensored") == "@PiersMorganUncensored"

def test_parse_channel_key_none():
    assert parse_channel_key(None) is None
    assert parse_channel_key("https://www.youtube.com/") is None
```
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement** `src/youtube.py` parsers:
```python
"""YouTube helpers: URL/channel parsing + fail-safe transcript/oEmbed fetch.

Pure parsers have no network. Network fetchers NEVER raise — they return a
sentinel so the API can degrade gracefully (spec §5).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def parse_video_id(url: str | None) -> str | None:
    """Extract an 11-char YouTube video id from common URL forms, else None."""
    if not url:
        return None
    try:
        u = urlparse(url.strip())
    except (ValueError, AttributeError):
        return None
    host = (u.netloc or "").lower().removeprefix("www.")
    if host == "youtu.be":
        cand = u.path.lstrip("/").split("/")[0]
        return cand if _VIDEO_ID_RE.match(cand) else None
    if host in ("youtube.com", "m.youtube.com", "music.youtube.com"):
        if u.path == "/watch":
            cand = (parse_qs(u.query).get("v") or [""])[0]
            return cand if _VIDEO_ID_RE.match(cand) else None
        for prefix in ("/shorts/", "/embed/", "/live/", "/v/"):
            if u.path.startswith(prefix):
                cand = u.path[len(prefix):].split("/")[0]
                return cand if _VIDEO_ID_RE.match(cand) else None
    return None


def parse_channel_key(author_url: str | None) -> str | None:
    """Stable channel key from an oEmbed author_url.

    Prefers a /channel/UC... id; falls back to an @handle (best-effort, V1);
    returns None when neither is derivable (caller then skips identity upsert).
    """
    if not author_url:
        return None
    try:
        path = urlparse(author_url).path or ""
    except (ValueError, AttributeError):
        return None
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    if parts[0] == "channel" and len(parts) > 1 and parts[1].startswith("UC"):
        return parts[1]
    if parts[0].startswith("@"):
        return parts[0]
    return None
```
- [ ] **Step 4 — add dep:** append to `requirements.txt`: `youtube-transcript-api` (pin the current latest; e.g. `youtube-transcript-api==<latest>`). Install into the venv.
- [ ] **Step 5 — run green** (`pytest tests/test_youtube.py -q`), then **commit**: `git add requirements.txt src/youtube.py tests/test_youtube.py` → `feat(youtube): video-id/channel-key parsers + youtube-transcript-api dep`

### Task A2: Fail-safe transcript fetch wrapper + live spike

**Files:** `src/youtube.py` (extend), `tests/test_youtube.py` (extend), `scripts/spike_youtube_transcript.py` (create)

- [ ] **Step 1 — failing tests** (mock the library symbol; version-agnostic):
```python
def test_fetch_transcript_success(monkeypatch):
    import src.youtube as yt
    class _Api:
        @staticmethod
        def get_transcript(vid, languages=None):
            return [{"text": "hello", "start": 1.0, "duration": 2.0}]
    monkeypatch.setattr(yt, "_get_transcript_raw", lambda vid: _Api.get_transcript(vid))
    ok, segs, reason = yt.fetch_transcript("abc")
    assert ok is True and segs[0]["text"] == "hello" and reason is None

def test_fetch_transcript_unavailable(monkeypatch):
    import src.youtube as yt
    def _boom(vid):
        raise RuntimeError("TranscriptsDisabled")
    monkeypatch.setattr(yt, "_get_transcript_raw", _boom)
    ok, segs, reason = yt.fetch_transcript("abc")
    assert ok is False and segs == [] and isinstance(reason, str)
```
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement** in `src/youtube.py`:
```python
def _get_transcript_raw(video_id: str) -> list[dict]:
    """Thin call to youtube-transcript-api, isolated for mocking + version adaptation.

    Adapt this single function to the installed library version (the A2 spike
    confirms the exact surface). Returns a list of {text, start, duration}.
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    return YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US"])


def fetch_transcript(video_id: str) -> tuple[bool, list[dict], str | None]:
    """(available, segments, reason). Never raises."""
    try:
        raw = _get_transcript_raw(video_id) or []
        segs = [
            {"text": s.get("text", ""), "start": float(s.get("start", 0.0)),
             "duration": float(s.get("duration", 0.0))}
            for s in raw
        ]
        if not segs:
            return False, [], "empty transcript"
        return True, segs, None
    except Exception as e:  # noqa: BLE001 — degrade, never raise
        logger.info("transcript unavailable for %s: %s", video_id, e.__class__.__name__)
        return False, [], e.__class__.__name__
```
- [ ] **Step 4 — run green.**
- [ ] **Step 5 — spike** (`scripts/spike_youtube_transcript.py`): resolve + fetch a known captioned public video, print availability + first 2 segments. Run it once locally:
```python
# scripts/spike_youtube_transcript.py
from src.youtube import fetch_transcript, parse_video_id
URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # replace with a known-captioned video
vid = parse_video_id(URL)
ok, segs, reason = fetch_transcript(vid)
print(f"video={vid} available={ok} reason={reason} n_segments={len(segs)}")
print(segs[:2])
```
- [ ] **Step 6 — report** in the PR/checkpoint: does transcript fetch work from this machine? (Treat EC2 reliability as a Phase-G/production smoke risk — datacenter IPs may be blocked.)
- [ ] **Step 7 — commit**: `git add src/youtube.py tests/test_youtube.py scripts/spike_youtube_transcript.py` → `feat(youtube): fail-safe transcript fetch wrapper + spike script`

> **Gate:** if the spike shows transcript fetch is fundamentally broken locally, STOP and report before proceeding — the watch view depends on it.

---

## Phase B — Migration 074

### Task B1: `schema/074_video_quotes.sql`

**Files:** `schema/074_video_quotes.sql` (create)

- [ ] **Step 1 — collision pre-check** (read-only): `SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename='video_quotes';` → expect 0 rows.
- [ ] **Step 2 — author** (mirror 073: `IF NOT EXISTS`, RLS enable-only, reuse `tg_credibility_set_updated_at`, ledger row):
```sql
-- schema/074_video_quotes.sql
-- Video Research / Quote Capture (Phase 1). Additive only. RLS on.
-- Stores ONLY saved quote excerpts (transcripts are fetched live, never persisted).

CREATE TABLE IF NOT EXISTS public.video_quotes (
    id                      SERIAL PRIMARY KEY,
    video_id                TEXT NOT NULL,
    video_url               TEXT NOT NULL,
    video_title             TEXT,
    channel_name            TEXT,
    channel_url             TEXT,
    quote_text              TEXT NOT NULL,
    start_seconds           NUMERIC NOT NULL,
    end_seconds             NUMERIC,
    person_id               INTEGER REFERENCES public.people(id) ON DELETE SET NULL,
    category_slug           TEXT REFERENCES public.credibility_categories(slug),
    ticker                  VARCHAR(20),
    stock_thesis_profile_id INTEGER REFERENCES public.stock_thesis_profiles(id) ON DELETE SET NULL,
    thesis_note             TEXT,
    tags                    TEXT[] NOT NULL DEFAULT '{}',
    notes                   TEXT,
    status                  text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    saved_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_video_quotes_video    ON public.video_quotes (video_id);
CREATE INDEX IF NOT EXISTS idx_video_quotes_person   ON public.video_quotes (person_id);
CREATE INDEX IF NOT EXISTS idx_video_quotes_category ON public.video_quotes (category_slug);
CREATE INDEX IF NOT EXISTS idx_video_quotes_ticker   ON public.video_quotes (UPPER(ticker));
CREATE INDEX IF NOT EXISTS idx_video_quotes_status   ON public.video_quotes (status);

DROP TRIGGER IF EXISTS video_quotes_updated_at ON public.video_quotes;
CREATE TRIGGER video_quotes_updated_at
    BEFORE UPDATE ON public.video_quotes
    FOR EACH ROW EXECUTE FUNCTION public.tg_credibility_set_updated_at();

ALTER TABLE public.video_quotes ENABLE ROW LEVEL SECURITY;

INSERT INTO public.schema_migrations (version, description)
VALUES ('074_video_quotes', 'Video research saved quote excerpts (YouTube)')
ON CONFLICT (version) DO NOTHING;
```
- [ ] **Step 3 — verify** the file mirrors 073's RLS/trigger style (open 073). Do NOT apply to live (Phase G gate). **Commit**: `git add schema/074_video_quotes.sql` → `feat(schema): migration 074 video_quotes (saved excerpts)`

### Task B2: Register in `expected_schemas.py`

- [ ] Add a `video_quotes` entry to `EXPECTED_SCHEMAS` (mirror an existing entry's shape): fields `id:integer, video_id:text, video_url:text, video_title:text, channel_name:text, channel_url:text, quote_text:text, start_seconds:numeric, end_seconds:numeric, person_id:integer, category_slug:text, ticker:text, stock_thesis_profile_id:integer, thesis_note:text, tags:array, notes:text, status:text, saved_at:timestamptz, updated_at:timestamptz`; `primary_keys: ["id"]`.
- [ ] Verify `python -c "import src.expected_schemas"` clean. **Commit**: `git add src/expected_schemas.py` → `chore(schema): register video_quotes in expected_schemas`

---

## Phase C — `videos.py` router: `POST /videos/resolve`

### Task C1: oEmbed metadata wrapper + router registration

**Files:** `src/youtube.py` (extend), `tests/test_youtube.py` (extend), `app/routes/videos.py` (create skeleton), `app/main.py` (register)

- [ ] **Step 1 — failing tests:** `fetch_oembed(url)` returns `{title, author_name, author_url}` on success and `{}` (never raises) on failure (mock `requests.get`).
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement** `fetch_oembed` in `src/youtube.py`:
```python
def fetch_oembed(url: str) -> dict:
    """YouTube oEmbed metadata (title/author). Never raises — {} on failure."""
    import requests
    try:
        r = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"}, timeout=8,
        )
        if r.status_code != 200:
            return {}
        d = r.json()
        return {"title": d.get("title"), "author_name": d.get("author_name"),
                "author_url": d.get("author_url")}
    except Exception:  # noqa: BLE001
        return {}
```
Create `app/routes/videos.py` with `router = APIRouter()` and register in `app/main.py` (mirror `people`: import + `app.include_router(videos.router, tags=["Video Research"], dependencies=[Depends(require_api_key)])`).
- [ ] **Step 4 — green + commit**: `git add src/youtube.py tests/test_youtube.py app/routes/videos.py app/main.py` → `feat(api): oEmbed wrapper + videos router skeleton`

### Task C2: `POST /videos/resolve` (parse → oEmbed → transcript → speaker)

**Files:** `app/routes/videos.py` (extend), `tests/test_videos_api.py` (create)

- [ ] **Step 1 — failing tests** (mock `src.youtube` fns + `execute_sql`/`transaction`; TestClient + `DISABLE_AUTH`):
  - unparseable URL → **400**.
  - valid URL, transcript available → 200 with `transcriptAvailable:true`, `segments`, and `suggestedPersonId` resolved from a confirmed identity (mock the confirmed lookup).
  - transcript unavailable (fetch_transcript → (False,[],"TranscriptsDisabled")) → 200, `transcriptAvailable:false`, `segments:[]`, `reason` set (NOT a 500).
  - oEmbed failure ({}) → 200 with null title/channel but transcript still attempted.
  - channel with no confirmed identity but a usable key → upserts a `suggested` source_identity (assert the upsert ran) and `suggestedPersonId` is null.
  - no derivable channel key → no identity upsert (assert execute_sql NOT called for the upsert path), still returns metadata/transcript.
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement** `POST /videos/resolve` body `{url}`:
  - `vid = parse_video_id(url)`; if None → `HTTPException(400, "Unparseable YouTube URL")`.
  - `meta = fetch_oembed(url)` (→ {} on fail).
  - `available, segments, reason = fetch_transcript(vid)`.
  - `key = parse_channel_key(meta.get("author_url"))`. Speaker resolution **only if key**:
    - confirmed lookup: `SELECT si.person_id, p.full_name FROM source_identities si JOIN people p ON p.id=si.person_id WHERE si.platform='youtube' AND si.platform_user_id=:key AND si.match_status='confirmed'` → `suggestedPersonId/Name`.
    - if no confirmed row → upsert suggested: `INSERT INTO source_identities (platform, platform_user_id, handle, match_status) VALUES ('youtube', :key, :handle, 'suggested') ON CONFLICT (platform, platform_user_id) DO NOTHING` (never overwrites a confirmed/conflict row; never creates a Person).
  - if no key → skip identity entirely.
  - Wrap speaker resolution in try/except (a DB hiccup must not 500 the resolve — fall back to null speaker).
  - Return `{ videoId, url, title, channelName, channelUrl, transcriptAvailable, reason, segments, suggestedPersonId, suggestedPersonName }`.
- [ ] **Step 4 — green** (`pytest tests/test_videos_api.py tests/test_youtube.py -q`) + **commit**: `feat(api): POST /videos/resolve (metadata + live transcript + speaker resolution)`

---

## Phase D — Quote CRUD

### Task D1: `POST /quotes` + `GET /quotes` (filters)

**Files:** `app/routes/videos.py` (extend), `tests/test_videos_api.py` (extend). Mirror `app/routes/people.py`.

- [ ] **Step 1 — failing tests:** POST creates a quote (assert INSERT params incl. all fields; `tags` default `[]`); GET lists with filters `q`/`person_id`/`category`/`ticker`/`video_id`/`status`, **defaults to `status='active'`** (archived hidden), and LEFT JOINs person/category labels.
- [ ] **Step 2 — run red.**
- [ ] **Step 3 — implement.** `QuoteBody` (camelCase): `videoId, videoUrl, videoTitle?, channelName?, channelUrl?, quoteText, startSeconds, endSeconds?, personId?, categorySlug?, ticker?, stockThesisProfileId?, thesisNote?, tags=[], notes?`. `POST /quotes` → INSERT (named params; `transaction()`); returns the created row id + echo. `GET /quotes` builds a WHERE from provided filters (always `status = :status` with default `'active'`; `q` → `quote_text ILIKE :q`; `UPPER(ticker)=UPPER(:ticker)`), LEFT JOIN `people`/`credibility_categories` for `personName`/`categoryLabel`, `ORDER BY saved_at DESC LIMIT 500`.
- [ ] **Step 4 — green + commit**: `feat(api): create + list video quotes (filters, active-by-default)`

### Task D2: `GET/PUT/DELETE /quotes/{id}`

- [ ] **Step 1 — failing tests:** GET detail (404 if missing); PUT updates associations/notes (re-bucket); DELETE soft-archives (`status='archived'`, assert UPDATE not hard delete).
- [ ] **Step 2-4:** implement mirroring people.py (advisory lock optional; named params), green, **commit**: `feat(api): get/update/archive video quotes`

> **Backend checkpoint:** `pytest tests/ -m "not openai and not integration"` all green; `ruff check src/ app/ tests/` clean.

---

## Phase E — Frontend `/research`: URL input + player + transcript

> Mirror `app/credibility/page.tsx`, `hooks/useCredibility.ts`, the `app/api/...` proxy shape (Next 15 `params: Promise<…>`, `authGuard()` + `backendFetch()`), and `Sidebar.tsx` nav. Branch `feature/video-research` off main in the frontend repo. Verify each task with `npm run build` (it lints too).

### Task E1: Types + API proxies + hooks

**Files (create):** `frontend/src/types/research.ts`; `app/api/videos/resolve/route.ts` (POST), `app/api/quotes/route.ts` (GET+POST), `app/api/quotes/[id]/route.ts` (GET+PUT+DELETE); `frontend/src/hooks/useResearch.ts` (+ barrel export).
- [ ] Types: `TranscriptSegment {text,start,duration}`, `ResolvedVideo {videoId,url,title,channelName,channelUrl,transcriptAvailable,reason,segments,suggestedPersonId,suggestedPersonName}`, `Quote {...all fields + personName, categoryLabel}`, `QuoteBodyInput {...}`.
- [ ] Proxies: thin `authGuard()` + `backendFetch()` (no bucket forwarding). `resolve` POSTs `{url}`. Forward backend status verbatim.
- [ ] Hooks: `useResolveVideo()` (an async action — POST, not SWR, since it's URL-triggered), `useQuotes(filters)` (SWR over `/api/quotes?…`), returning `{quotes, isLoading, refresh}`.
- [ ] **Verify** `npm run build`. **Commit**: `feat(fe): research types, api proxies, hooks`

### Task E2: `/research` page + IFrame player + synced transcript

**Files (create):** `app/research/page.tsx`; `components/research/{VideoPlayer,TranscriptViewer}.tsx`. **Modify:** `Sidebar.tsx` (add "Research" nav entry, an appropriate heroicon).
- [ ] Page (`'use client'`, Sidebar+TopBar layout): URL input + Load → `useResolveVideo`. On success render `VideoPlayer` (embed `https://www.youtube.com/embed/{videoId}` via the **IFrame Player API**) + `TranscriptViewer` (renders `segments`). If `!transcriptAvailable` → show player + a "No transcript available (reason)" banner.
- [ ] **Sync:** poll `player.getCurrentTime()` ~250ms while playing → highlight + auto-scroll the active segment; click a segment → `player.seekTo(start)`. Graceful degradation: if the player API fails, transcript stays a clickable static list.
- [ ] Empty/error states handled (no URL yet, resolve error, no captions). **Verify** `npm run build`. **Commit**: `feat(fe): /research workspace with synced video + transcript`

---

## Phase F — Quote capture drawer + library

**Files (create):** `components/research/{CaptureDrawer,QuoteLibrary,QuoteCard}.tsx`. **Modify:** `app/research/page.tsx` (wire selection→drawer + a Library tab).

### Task F1: Capture drawer
- [ ] Select one or more contiguous transcript segments → a drawer opens prefilled: `quoteText` (joined, editable), `startSeconds` (first), `endSeconds` (last), speaker (prefilled from `suggestedPerson`, `usePeople` select + create-person link), bucket (`useCredibilityCategories` select), ticker, stock thesis (optional pick), thesis note (textarea), tags, notes. Save → `POST /api/quotes` → toast + clear selection.
- [ ] **Verify** `npm run build`. **Commit**: `feat(fe): quote capture drawer`

### Task F2: Quote library tab
- [ ] A "Library" tab/section in `/research`: `useQuotes(filters)` with filter controls (text `q`, person, category, ticker, status). `QuoteCard`: quote text, speaker, bucket chip, tags, **source deep-link** `…watch?v={videoId}&t={Math.floor(startSeconds)}s`, notes; edit (PUT) + archive (DELETE) actions. Empty state when no quotes.
- [ ] **Verify** `npm run build`. **Commit**: `feat(fe): quote library tab (filters, timestamp deep-links, edit/archive)`

---

## Phase G — Verification, migration gate, PRs/deploy

- [ ] **Backend:** `pytest tests/ -q --no-header -m "not openai and not integration"` green; `ruff check src/ app/ tests/` clean.
- [ ] **Frontend:** `npm run build` green.
- [ ] **Push** both `feature/video-research` branches; **open PRs** (backend + frontend) against `main` with test/build results + a note that migration 074 is pending live application and the `youtube-transcript-api` spike result.
- [ ] **Migration 074 → live Supabase:** GATED on explicit owner approval. When approved: `python scripts/deploy_database.py`; verify `video_quotes` exists + RLS on + ledger row. Then merge backend → watch EC2 deploy + `/health` + smoke `GET /quotes` (401 unauth = deployed) and `POST /videos/resolve` against a real video (the EC2 transcript-reliability check). Then merge frontend → watch Vercel.
- [ ] Manual smoke: `/research` loads, paste a captioned video → transcript renders + syncs, select → save a quote, library shows it with a working timestamp deep-link, archived hidden by default.

---

## Self-review notes (author)

- **Spec coverage:** A (transcript spike §5 + parsers), B (data model §4), C (resolve §5/§6 incl. never-500 + channel-key rules), D (quotes CRUD §6 + filters), E/F (UI §7), G (guardrails §10 + migration gate). ✔
- **Refinements honored:** channel-key prefers `/channel/UC…`, `@handle` best-effort, skip upsert when no key, never auto-create Person (C2); resolve never 500s, 400 only on bad URL, oEmbed→null-not-fatal, transcript→`available:false/reason` (C2); library filters `q/person_id/category/ticker/video_id/status` default active (D1); `start_seconds`+`end_seconds` stored + `&t=` deep-link (B1/F2); early spike (A2). ✔
- **Type consistency:** `fetch_transcript` returns `(bool, list, str|None)` used identically in C2; `ResolvedVideo`/`Quote` fields match the backend `/videos/resolve` + `/quotes` payloads. ✔
- **Mechanical FE tasks** mirror named credibility templates rather than reproducing every line; each cites its template + has verify/commit steps. Acknowledged tradeoff.
