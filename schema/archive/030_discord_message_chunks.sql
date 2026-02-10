-- Migration: 030_discord_message_chunks
-- Description: Create table for chunked Discord messages for NLP processing
-- Date: 2025-12-12

-- Table: discord_message_chunks
-- Stores pre-processed message chunks for SetFit classification and LLM extraction
CREATE TABLE IF NOT EXISTS "public"."discord_message_chunks" (
    "message_id" text NOT NULL,
    "chunk_index" integer NOT NULL,
    "chunk_text" text NOT NULL,
    "channel_id" text,
    "author_id" text,
    "source_table" text,  -- 'discord_trading_clean' or 'discord_market_clean'
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    -- SetFit classification results
    "setfit_labels" text[],
    "setfit_scores" jsonb,
    "setfit_model_version" text,
    "setfit_classified_at" timestamp with time zone,
    -- Metadata
    "char_count" integer,
    "word_count" integer,
    CONSTRAINT "discord_message_chunks_pkey" PRIMARY KEY ("message_id", "chunk_index")
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS "idx_chunks_source_table" 
    ON "public"."discord_message_chunks" ("source_table");

CREATE INDEX IF NOT EXISTS "idx_chunks_setfit_model_version" 
    ON "public"."discord_message_chunks" ("setfit_model_version");

CREATE INDEX IF NOT EXISTS "idx_chunks_unclassified" 
    ON "public"."discord_message_chunks" ("message_id") 
    WHERE "setfit_model_version" IS NULL;

CREATE INDEX IF NOT EXISTS "idx_chunks_labels" 
    ON "public"."discord_message_chunks" USING GIN ("setfit_labels");

-- Enable RLS
ALTER TABLE "public"."discord_message_chunks" ENABLE ROW LEVEL SECURITY;

-- RLS Policies
CREATE POLICY "Enable read access for all users" 
    ON "public"."discord_message_chunks" 
    FOR SELECT USING (true);

CREATE POLICY "Enable insert for authenticated users" 
    ON "public"."discord_message_chunks" 
    FOR INSERT WITH CHECK (true);

CREATE POLICY "Enable update for authenticated users" 
    ON "public"."discord_message_chunks" 
    FOR UPDATE USING (true);

-- Grant permissions
GRANT ALL ON TABLE "public"."discord_message_chunks" TO "anon";
GRANT ALL ON TABLE "public"."discord_message_chunks" TO "authenticated";
GRANT ALL ON TABLE "public"."discord_message_chunks" TO "service_role";

-- Record migration
INSERT INTO "public"."schema_migrations" ("version", "description", "applied_at")
VALUES ('030', 'Create discord_message_chunks table for NLP pipeline', CURRENT_TIMESTAMP)
ON CONFLICT ("version") DO NOTHING;
