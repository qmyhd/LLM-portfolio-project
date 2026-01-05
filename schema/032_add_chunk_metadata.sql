-- Migration: 032_add_chunk_metadata
-- Description: Add deterministic metadata columns to discord_message_chunks for NLP pipeline
-- Date: 2025-12-12

-- Add chunk classification columns
ALTER TABLE "public"."discord_message_chunks"
ADD COLUMN IF NOT EXISTS "chunk_type" text,
ADD COLUMN IF NOT EXISTS "context_tickers" text[],
ADD COLUMN IF NOT EXISTS "symbols_detected" text[],
ADD COLUMN IF NOT EXISTS "n_symbols" integer DEFAULT 0,
ADD COLUMN IF NOT EXISTS "has_price" boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS "has_levels_language" boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS "has_link" boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS "has_image" boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS "is_question" boolean DEFAULT false,
ADD COLUMN IF NOT EXISTS "time_horizon_hint" text,
ADD COLUMN IF NOT EXISTS "gate_to_extraction" boolean DEFAULT true,
ADD COLUMN IF NOT EXISTS "chunk_hash" text;

-- Add check constraint for chunk_type
ALTER TABLE "public"."discord_message_chunks"
DROP CONSTRAINT IF EXISTS "discord_message_chunks_chunk_type_check";

ALTER TABLE "public"."discord_message_chunks"
ADD CONSTRAINT "discord_message_chunks_chunk_type_check" CHECK (
    "chunk_type" IS NULL OR "chunk_type" IN (
        'TICKER_SECTION', 
        'BULLET', 
        'PARAGRAPH', 
        'LINK_ONLY', 
        'COMMAND', 
        'TICKER_LIST'
    )
);

-- Add check constraint for time_horizon_hint
ALTER TABLE "public"."discord_message_chunks"
DROP CONSTRAINT IF EXISTS "discord_message_chunks_time_horizon_check";

ALTER TABLE "public"."discord_message_chunks"
ADD CONSTRAINT "discord_message_chunks_time_horizon_check" CHECK (
    "time_horizon_hint" IS NULL OR "time_horizon_hint" IN (
        'scalp',
        'day', 
        'swing',
        'week',
        'month',
        'long_term',
        'unknown'
    )
);

-- Add unique constraint on chunk_hash (for idempotent UPSERT)
-- Note: chunk_hash includes message_id + chunk_index + normalized text hash
CREATE UNIQUE INDEX IF NOT EXISTS "idx_chunks_hash_unique"
    ON "public"."discord_message_chunks" ("chunk_hash")
    WHERE "chunk_hash" IS NOT NULL;

-- Add GIN indexes for array columns (efficient contains queries)
CREATE INDEX IF NOT EXISTS "idx_chunks_symbols_detected_gin"
    ON "public"."discord_message_chunks" USING GIN ("symbols_detected");

CREATE INDEX IF NOT EXISTS "idx_chunks_context_tickers_gin"
    ON "public"."discord_message_chunks" USING GIN ("context_tickers");

-- Add index for gate_to_extraction (filter chunks needing LLM extraction)
CREATE INDEX IF NOT EXISTS "idx_chunks_gate_to_extraction"
    ON "public"."discord_message_chunks" ("gate_to_extraction")
    WHERE "gate_to_extraction" = true;

-- Add index for chunk_type
CREATE INDEX IF NOT EXISTS "idx_chunks_chunk_type"
    ON "public"."discord_message_chunks" ("chunk_type")
    WHERE "chunk_type" IS NOT NULL;

-- Record migration
INSERT INTO "public"."schema_migrations" ("version", "description", "applied_at")
VALUES ('032', 'Add chunk metadata columns for deterministic NLP features', CURRENT_TIMESTAMP)
ON CONFLICT ("version") DO NOTHING;
