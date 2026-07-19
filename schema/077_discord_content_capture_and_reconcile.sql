-- =======================================================================
-- Migration 077: Discord content capture + parse-queue reconciliation
-- =======================================================================
-- Already applied to production via Supabase (registered in schema_migrations).
--
-- Problems fixed:
--  1. Live ingestion (log_message_to_database) never wrote tweet_urls, so
--     238 messages containing X/Twitter links had tweet_urls = NULL and the
--     shared-tweet content was effectively lost.
--  2. The NLP parser only selects pending messages with >10 chars of real,
--     non-bot/command content. Empty/short/bot/command messages therefore sat
--     in parse_status='pending' forever (211 of them), never classified.
--  3. No column captured Discord's embed unfurl (which contains the tweet text
--     for shared X links) — the cheapest way to keep that content without the
--     paid Twitter API.

-- 1. Store Discord embed payloads (unfurled tweet/link text) going forward.
ALTER TABLE public.discord_messages ADD COLUMN IF NOT EXISTS embeds TEXT;

-- 2. Backfill tweet_urls from existing message content.
UPDATE public.discord_messages d
SET tweet_urls = sub.urls
FROM (
  SELECT message_id, string_agg(url, ', ') AS urls
  FROM (
    SELECT message_id,
           (regexp_matches(content,
             'https?://(?:www\.|mobile\.)?(?:twitter\.com|x\.com|t\.co|fxtwitter\.com|vxtwitter\.com|nitter\.[a-z]+)/[^\s]+',
             'g'))[1] AS url
    FROM public.discord_messages
    WHERE content ~* '(twitter\.com|x\.com/|t\.co/)'
  ) x
  GROUP BY message_id
) sub
WHERE d.message_id = sub.message_id
  AND (d.tweet_urls IS NULL OR d.tweet_urls = '');

-- 3. Reconcile the parse queue: non-parseable pending -> skipped.
UPDATE public.discord_messages
SET parse_status = 'skipped',
    error_reason = 'auto-skip: non-parseable (empty/short/bot/command)'
WHERE parse_status = 'pending'
  AND NOT (
    content IS NOT NULL
    AND length(trim(content)) > 10
    AND COALESCE(is_bot, false) = false
    AND COALESCE(is_command, false) = false
  );

INSERT INTO public.schema_migrations (version, description)
VALUES ('077_discord_content_capture_and_reconcile',
        'Add embeds column, backfill tweet_urls from content, sweep non-parseable pending to skipped')
ON CONFLICT (version) DO NOTHING;
