#!/usr/bin/env python3
"""
Backfill tweet text for historically-shared X/Twitter links.

Many `discord_messages` carry a `tweet_urls` value (a shared X link) but no
tweet text — the live ingestion only started capturing Discord embed text
later, and the Twitter API tier no longer allows tweet reads. This script
fetches the tweet text for those messages from the free, auth-less fxtwitter
API and stores it in the `embeds` column (same JSON shape the NLP parser reads
via `_extract_embed_text`), so the shared tweet's actual claims become
parseable content.

Store-only by default. Pass --reparse to also flip the enriched messages back
to parse_status='pending' so the next NLP batch re-evaluates them WITH the
tweet text (this costs OpenAI credits — ~one mini-model call per message).

Usage:
    python scripts/backfill_tweet_text.py [--limit N] [--reparse] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

from src.db import execute_sql  # noqa: E402

# Matches the status id from twitter.com / x.com / fxtwitter / etc. links.
_TWEET_ID_RE = re.compile(r"(?:twitter\.com|x\.com|fxtwitter\.com|vxtwitter\.com|nitter\.[a-z]+)/[^/\s]+/status(?:es)?/(\d+)")
_FX_API = "https://api.fxtwitter.com/status/{id}"
_HEADERS = {"User-Agent": "llm-portfolio-journal/1.0 (tweet backfill)"}


def extract_tweet_ids(tweet_urls: str) -> list[str]:
    """All distinct tweet IDs referenced in a comma-separated tweet_urls value."""
    ids: list[str] = []
    for m in _TWEET_ID_RE.finditer(tweet_urls or ""):
        tid = m.group(1)
        if tid not in ids:
            ids.append(tid)
    return ids


def fetch_tweet(tweet_id: str) -> dict | None:
    """Return {text, author, url} for a tweet id, or None on any failure."""
    try:
        resp = requests.get(_FX_API.format(id=tweet_id), headers=_HEADERS, timeout=12)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    try:
        tweet = (resp.json() or {}).get("tweet") or {}
    except ValueError:
        return None
    text = (tweet.get("text") or "").strip()
    if not text:
        return None
    author = (tweet.get("author") or {}).get("screen_name")
    return {
        "text": text,
        "author": f"@{author}" if author else None,
        "url": tweet.get("url"),
    }


def build_embed_json(fetched: list[dict]) -> str:
    """Shape the fetched tweets like the ingestion's embeds column."""
    return json.dumps(
        [
            {
                "type": "tweet_backfill",
                "title": None,
                "description": f["text"],
                "url": f.get("url"),
                "author": f.get("author"),
            }
            for f in fetched
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Max messages to process")
    parser.add_argument("--reparse", action="store_true", help="Queue enriched messages for NLP re-parse (costs OpenAI)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch + report, no DB writes")
    parser.add_argument("--sleep", type=float, default=0.4, help="Seconds between API calls")
    args = parser.parse_args()

    # Messages with a shared tweet link but no embed content captured yet.
    query = """
        SELECT message_id, tweet_urls
        FROM discord_messages
        WHERE tweet_urls IS NOT NULL AND tweet_urls <> ''
          AND (embeds IS NULL OR embeds = '' OR embeds = '[]')
        ORDER BY created_at DESC
    """
    if args.limit:
        query += f" LIMIT {int(args.limit)}"
    rows = execute_sql(query, fetch_results=True) or []
    print(f"Found {len(rows)} messages with tweet links and no captured text.")

    enriched = failed = skipped = reparsed = 0
    for row in rows:
        message_id = str(row[0])
        tweet_urls = row[1]
        ids = extract_tweet_ids(tweet_urls)
        if not ids:
            skipped += 1
            continue

        fetched = []
        for tid in ids:
            data = fetch_tweet(tid)
            if data:
                fetched.append(data)
            time.sleep(args.sleep)

        if not fetched:
            failed += 1
            print(f"  [x] {message_id}: no tweet text recovered ({len(ids)} id(s))")
            continue

        preview = fetched[0]["text"][:80].replace("\n", " ")
        print(f"  [ok] {message_id}: {fetched[0].get('author') or '?'} - {preview}")
        enriched += 1

        if args.dry_run:
            continue

        execute_sql(
            "UPDATE discord_messages SET embeds = CAST(:embeds AS TEXT) WHERE message_id = :mid",
            params={"embeds": build_embed_json(fetched), "mid": message_id},
        )
        if args.reparse:
            execute_sql(
                """
                UPDATE discord_messages
                SET parse_status = 'pending', error_reason = NULL
                WHERE message_id = :mid
                  AND NOT EXISTS (
                    SELECT 1 FROM discord_parsed_ideas dpi
                    WHERE dpi.message_id = discord_messages.message_id
                      AND dpi.review_status <> 'unreviewed'
                  )
                """,
                params={"mid": message_id},
            )
            reparsed += 1

    print("\n=== Summary ===")
    print(f"  enriched:  {enriched}")
    print(f"  failed:    {failed} (deleted/protected/private tweets)")
    print(f"  skipped:   {skipped} (no parseable tweet id)")
    if args.reparse:
        print(f"  reparsed:  {reparsed} (queued for next NLP batch)")
    if args.dry_run:
        print("  (dry-run — no writes performed)")
    elif enriched and not args.reparse:
        print("  Tip: re-run with --reparse to feed this text into the NLP pipeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
