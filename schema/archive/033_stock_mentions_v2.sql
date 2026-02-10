-- Migration: 033_stock_mentions_v2
-- Description: Restructure stock_mentions for proper mention-level extraction
-- Date: 2025-12-12
-- 
-- Changes:
-- 1. Rename mention_type -> instrument (actual asset type)
-- 2. Add mention_kind (trade, level, thesis, catalyst, sentiment, other)
-- 3. Add side (long, short, unknown)
-- 4. Add order_style_hint (market, limit, scale_in, scale_out, unknown)
-- 5. Add options jsonb for derivatives
-- 6. Add source_span_start/end for text highlighting
-- 7. Add confidence score

-- Step 1: Add new columns
ALTER TABLE "public"."stock_mentions"
ADD COLUMN IF NOT EXISTS "mention_kind" text,
ADD COLUMN IF NOT EXISTS "instrument" text,
ADD COLUMN IF NOT EXISTS "side" text,
ADD COLUMN IF NOT EXISTS "order_style_hint" text,
ADD COLUMN IF NOT EXISTS "options" jsonb,
ADD COLUMN IF NOT EXISTS "catalyst" text,
ADD COLUMN IF NOT EXISTS "source_span_start" integer,
ADD COLUMN IF NOT EXISTS "source_span_end" integer,
ADD COLUMN IF NOT EXISTS "confidence" numeric(5,4);

-- Step 2: Migrate existing mention_type data to instrument column
UPDATE "public"."stock_mentions" 
SET "instrument" = "mention_type"
WHERE "instrument" IS NULL AND "mention_type" IS NOT NULL;

-- Step 3: Drop old constraint and add new ones
ALTER TABLE "public"."stock_mentions"
DROP CONSTRAINT IF EXISTS "stock_mentions_mention_type_check";

-- Add instrument check (asset types - what mention_type should have been)
ALTER TABLE "public"."stock_mentions"
DROP CONSTRAINT IF EXISTS "stock_mentions_instrument_check";

ALTER TABLE "public"."stock_mentions"
ADD CONSTRAINT "stock_mentions_instrument_check" CHECK (
    "instrument" IS NULL OR "instrument" IN (
        'equity', 'option', 'crypto', 'etf', 'index', 'event_contract', 'unknown'
    )
);

-- Add mention_kind check (what the mention IS about)
ALTER TABLE "public"."stock_mentions"
DROP CONSTRAINT IF EXISTS "stock_mentions_mention_kind_check";

ALTER TABLE "public"."stock_mentions"
ADD CONSTRAINT "stock_mentions_mention_kind_check" CHECK (
    "mention_kind" IS NULL OR "mention_kind" IN (
        'trade', 'level', 'thesis', 'catalyst', 'sentiment', 'other'
    )
);

-- Add side check
ALTER TABLE "public"."stock_mentions"
DROP CONSTRAINT IF EXISTS "stock_mentions_side_check";

ALTER TABLE "public"."stock_mentions"
ADD CONSTRAINT "stock_mentions_side_check" CHECK (
    "side" IS NULL OR "side" IN ('long', 'short', 'unknown')
);

-- Add order_style_hint check
ALTER TABLE "public"."stock_mentions"
DROP CONSTRAINT IF EXISTS "stock_mentions_order_style_hint_check";

ALTER TABLE "public"."stock_mentions"
ADD CONSTRAINT "stock_mentions_order_style_hint_check" CHECK (
    "order_style_hint" IS NULL OR "order_style_hint" IN (
        'market', 'limit', 'scale_in', 'scale_out', 'unknown'
    )
);

-- Add confidence check (0.0000 to 1.0000)
ALTER TABLE "public"."stock_mentions"
DROP CONSTRAINT IF EXISTS "stock_mentions_confidence_check";

ALTER TABLE "public"."stock_mentions"
ADD CONSTRAINT "stock_mentions_confidence_check" CHECK (
    "confidence" IS NULL OR ("confidence" >= 0 AND "confidence" <= 1)
);

-- Step 4: Update unique constraint for mention-level rows
-- Drop old unique constraint
ALTER TABLE "public"."stock_mentions"
DROP CONSTRAINT IF EXISTS "stock_mentions_unique";

-- Create new unique constraint that allows multiple mentions per symbol
-- Key: (message_id, chunk_index, symbol, mention_kind, action)
ALTER TABLE "public"."stock_mentions"
ADD CONSTRAINT "stock_mentions_unique_v2" UNIQUE (
    "message_id", "chunk_index", "symbol", "mention_kind", "action"
);

-- Step 5: Add new indexes
CREATE INDEX IF NOT EXISTS "idx_stock_mentions_mention_kind"
    ON "public"."stock_mentions" ("mention_kind")
    WHERE "mention_kind" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_instrument"
    ON "public"."stock_mentions" ("instrument")
    WHERE "instrument" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_side"
    ON "public"."stock_mentions" ("side")
    WHERE "side" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_chunk"
    ON "public"."stock_mentions" ("message_id", "chunk_index");

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_levels_gin"
    ON "public"."stock_mentions" USING GIN ("levels");

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_options_gin"
    ON "public"."stock_mentions" USING GIN ("options")
    WHERE "options" IS NOT NULL;

-- Record migration
INSERT INTO "public"."schema_migrations" ("version", "description", "applied_at")
VALUES ('033', 'Restructure stock_mentions for mention-level extraction', CURRENT_TIMESTAMP)
ON CONFLICT ("version") DO NOTHING;
