-- Migration: 031_stock_mentions
-- Description: Create table for extracted stock mentions from messages
-- Date: 2025-12-12

-- Table: stock_mentions
-- Stores structured stock mention extractions from LLM processing
CREATE TABLE IF NOT EXISTS "public"."stock_mentions" (
    "id" bigserial,
    "message_id" text NOT NULL,
    "chunk_index" integer NOT NULL DEFAULT 0,
    "symbol" text NOT NULL,
    "mention_type" text NOT NULL,
    "action" text,
    "levels" jsonb,  -- Array of {kind, value, low, high, qualifier}
    "sentiment" text,
    "conviction" integer,  -- 0-100 scale
    "time_horizon" text,
    "model" text,
    "model_version" text,
    "raw_extraction" jsonb,  -- Full LLM response for debugging
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "stock_mentions_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "stock_mentions_unique" UNIQUE ("message_id", "chunk_index", "symbol", "mention_type"),
    -- Enum-like constraints
    CONSTRAINT "stock_mentions_mention_type_check" CHECK (
        "mention_type" IN ('ticker', 'option', 'event_contract', 'sector', 'index', 'crypto')
    ),
    CONSTRAINT "stock_mentions_action_check" CHECK (
        "action" IS NULL OR "action" IN ('buy', 'sell', 'trim', 'add', 'watch', 'hold', 'unknown')
    ),
    CONSTRAINT "stock_mentions_sentiment_check" CHECK (
        "sentiment" IS NULL OR "sentiment" IN ('bullish', 'bearish', 'neutral', 'mixed')
    ),
    CONSTRAINT "stock_mentions_conviction_check" CHECK (
        "conviction" IS NULL OR ("conviction" >= 0 AND "conviction" <= 100)
    )
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS "idx_stock_mentions_symbol" 
    ON "public"."stock_mentions" ("symbol");

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_message_id" 
    ON "public"."stock_mentions" ("message_id");

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_action" 
    ON "public"."stock_mentions" ("action") 
    WHERE "action" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_sentiment" 
    ON "public"."stock_mentions" ("sentiment") 
    WHERE "sentiment" IS NOT NULL;

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_created_at" 
    ON "public"."stock_mentions" ("created_at");

CREATE INDEX IF NOT EXISTS "idx_stock_mentions_model_version" 
    ON "public"."stock_mentions" ("model_version");

-- Enable RLS
ALTER TABLE "public"."stock_mentions" ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "Enable read access for all users" 
    ON "public"."stock_mentions" 
    FOR SELECT USING (true);

CREATE POLICY "Enable insert for authenticated users" 
    ON "public"."stock_mentions" 
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Enable update for authenticated users" 
    ON "public"."stock_mentions" 
    FOR UPDATE USING (true);

-- Grant permissions
GRANT ALL ON TABLE "public"."stock_mentions" TO "anon";
GRANT ALL ON TABLE "public"."stock_mentions" TO "authenticated";
GRANT ALL ON TABLE "public"."stock_mentions" TO "service_role";

-- Grant sequence permissions
GRANT USAGE, SELECT ON SEQUENCE "public"."stock_mentions_id_seq" TO "anon";
GRANT USAGE, SELECT ON SEQUENCE "public"."stock_mentions_id_seq" TO "authenticated";
GRANT USAGE, SELECT ON SEQUENCE "public"."stock_mentions_id_seq" TO "service_role";

-- Record migration
INSERT INTO "public"."schema_migrations" ("version", "description", "applied_at")
VALUES ('031', 'Create stock_mentions table for LLM extraction results', CURRENT_TIMESTAMP)
ON CONFLICT ("version") DO NOTHING;
