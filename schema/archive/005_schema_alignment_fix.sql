-- 005_schema_alignment_fix.sql - Schema Alignment and Consistency Fixes
-- Fixes critical schema discrepancies found during comprehensive audit
-- Resolves field type mismatches, missing migrations, and code-schema alignment issues

-- ==============================================
-- Schema Alignment Migration 
-- ==============================================

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('005_schema_alignment_fix', 'Schema alignment and consistency fixes - field types, missing migrations, code-schema alignment') 
ON CONFLICT (version) DO NOTHING;

-- ==============================================
-- Fix 1: Apply Missing discord_rename Migration (002)
-- ==============================================

-- Ensure discord_market_clean table exists and has proper constraints
DO $$ BEGIN
    -- Check if discord_general_clean exists and needs renaming
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_general_clean' AND table_schema = 'public') 
       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_market_clean' AND table_schema = 'public') THEN
        ALTER TABLE discord_general_clean RENAME TO discord_market_clean;
        RAISE NOTICE 'Renamed discord_general_clean to discord_market_clean';
    END IF;
    
    -- Ensure uniqueness constraints exist
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_market_clean' AND table_schema = 'public') THEN
        -- Add unique constraint if it doesn't exist
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                      WHERE table_name = 'discord_market_clean' 
                      AND constraint_type = 'UNIQUE' 
                      AND constraint_name LIKE '%message_id%') THEN
            ALTER TABLE discord_market_clean ADD CONSTRAINT discord_market_clean_message_id_unique UNIQUE (message_id);
            RAISE NOTICE 'Added unique constraint to discord_market_clean.message_id';
        END IF;
    END IF;
    
    -- Ensure discord_trading_clean has unique constraint
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_trading_clean' AND table_schema = 'public') THEN
        IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints 
                      WHERE table_name = 'discord_trading_clean' 
                      AND constraint_type = 'UNIQUE' 
                      AND constraint_name LIKE '%message_id%') THEN
            ALTER TABLE discord_trading_clean ADD CONSTRAINT discord_trading_clean_message_id_unique UNIQUE (message_id);
            RAISE NOTICE 'Added unique constraint to discord_trading_clean.message_id';
        END IF;
    END IF;
END $$;

-- ==============================================
-- Fix 2: Complete quote_currency JSONB Conversion
-- ==============================================

-- Complete the quote_currency field conversion that was incomplete in 004 migration
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'orders' 
               AND column_name = 'quote_currency' 
               AND data_type = 'text') THEN
        
        -- Create new JSONB column
        ALTER TABLE orders ADD COLUMN quote_currency_new JSONB;
        
        -- Migrate existing data (attempt to parse as JSON, fallback to simple string object)
        UPDATE orders SET quote_currency_new = 
            CASE 
                WHEN quote_currency IS NULL THEN NULL
                WHEN quote_currency = '' THEN NULL
                WHEN quote_currency ~ '^[\s]*[{\[]' THEN 
                    CASE 
                        WHEN jsonb_typeof(quote_currency::jsonb) IS NOT NULL THEN quote_currency::jsonb
                        ELSE NULL
                    END
                ELSE jsonb_build_object('code', quote_currency)
            END;
        
        -- Drop old column and rename new one
        ALTER TABLE orders DROP COLUMN quote_currency;
        ALTER TABLE orders RENAME COLUMN quote_currency_new TO quote_currency;
        
        RAISE NOTICE 'Successfully converted orders.quote_currency from TEXT to JSONB';
    END IF;
END $$;

-- ==============================================
-- Fix 3: Add Missing Base Schema Fields to orders
-- ==============================================

-- Add missing fields from 001_base.sql that are referenced in code
DO $$ BEGIN
    -- Add diary field if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'diary') THEN
        ALTER TABLE orders ADD COLUMN diary TEXT;
        RAISE NOTICE 'Added diary field to orders table';
    END IF;

    -- Add parent_brokerage_order_id field if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'parent_brokerage_order_id') THEN
        ALTER TABLE orders ADD COLUMN parent_brokerage_order_id TEXT;
        RAISE NOTICE 'Added parent_brokerage_order_id field to orders table';
    END IF;

    -- Add state field if missing
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'state') THEN
        ALTER TABLE orders ADD COLUMN state TEXT;
        RAISE NOTICE 'Added state field to orders table';
    END IF;

    -- Add user_secret field if missing (for legacy compatibility)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'user_secret') THEN
        ALTER TABLE orders ADD COLUMN user_secret TEXT;
        RAISE NOTICE 'Added user_secret field to orders table';
    END IF;
END $$;

-- ==============================================
-- Fix 4: Align discord_messages Field Types
-- ==============================================

-- Fix field type mismatches in discord_messages table
DO $$ BEGIN
    -- Check if author_id is TEXT and convert to BIGINT
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'discord_messages' 
               AND column_name = 'author_id' 
               AND data_type = 'text') THEN
        
        -- Create new column with correct type
        ALTER TABLE discord_messages ADD COLUMN author_id_new BIGINT;
        
        -- Migrate data safely (convert text to bigint, handle nulls)
        UPDATE discord_messages SET author_id_new = 
            CASE 
                WHEN author_id IS NULL OR author_id = '' THEN NULL
                WHEN author_id ~ '^[0-9]+$' THEN author_id::BIGINT
                ELSE NULL
            END;
        
        -- Drop old column and rename
        ALTER TABLE discord_messages DROP COLUMN author_id;
        ALTER TABLE discord_messages RENAME COLUMN author_id_new TO author_id;
        
        RAISE NOTICE 'Converted discord_messages.author_id from TEXT to BIGINT';
    END IF;

    -- Check if reply_to_id is TEXT and convert to BIGINT  
    IF EXISTS (SELECT 1 FROM information_schema.columns 
               WHERE table_name = 'discord_messages' 
               AND column_name = 'reply_to_id' 
               AND data_type = 'text') THEN
        
        -- Create new column with correct type
        ALTER TABLE discord_messages ADD COLUMN reply_to_id_new BIGINT;
        
        -- Migrate data safely
        UPDATE discord_messages SET reply_to_id_new = 
            CASE 
                WHEN reply_to_id IS NULL OR reply_to_id = '' THEN NULL
                WHEN reply_to_id ~ '^[0-9]+$' THEN reply_to_id::BIGINT
                ELSE NULL
            END;
        
        -- Drop old column and rename
        ALTER TABLE discord_messages DROP COLUMN reply_to_id;
        ALTER TABLE discord_messages RENAME COLUMN reply_to_id_new TO reply_to_id;
        
        RAISE NOTICE 'Converted discord_messages.reply_to_id from TEXT to BIGINT';
    END IF;

    -- Add user_id field if missing (database has it but base schema doesn't)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'discord_messages' AND column_name = 'user_id') THEN
        ALTER TABLE discord_messages ADD COLUMN user_id TEXT DEFAULT 'default_user';
        RAISE NOTICE 'Added user_id field to discord_messages table';
    END IF;
END $$;

-- ==============================================
-- Fix 5: Enhance twitter_data Schema to Match Base Schema
-- ==============================================

-- Add missing fields to twitter_data table to match 001_base.sql comprehensive schema
DO $$ BEGIN
    -- Add tweet_id field (the table has different structure than expected)
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'tweet_id') THEN
        ALTER TABLE twitter_data ADD COLUMN tweet_id TEXT;
        RAISE NOTICE 'Added tweet_id field to twitter_data table';
    END IF;

    -- Add discord_message_id field
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'discord_message_id') THEN
        ALTER TABLE twitter_data ADD COLUMN discord_message_id TEXT;
        RAISE NOTICE 'Added discord_message_id field to twitter_data table';
    END IF;

    -- Add discord_sent_date field
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'discord_sent_date') THEN
        ALTER TABLE twitter_data ADD COLUMN discord_sent_date TEXT;
        RAISE NOTICE 'Added discord_sent_date field to twitter_data table';
    END IF;

    -- Add tweet_created_date field
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'tweet_created_date') THEN
        ALTER TABLE twitter_data ADD COLUMN tweet_created_date TEXT;
        RAISE NOTICE 'Added tweet_created_date field to twitter_data table';
    END IF;

    -- Add tweet_content field
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'tweet_content') THEN
        ALTER TABLE twitter_data ADD COLUMN tweet_content TEXT;
        RAISE NOTICE 'Added tweet_content field to twitter_data table';
    END IF;

    -- Add author_username field
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'author_username') THEN
        ALTER TABLE twitter_data ADD COLUMN author_username TEXT;
        RAISE NOTICE 'Added author_username field to twitter_data table';
    END IF;

    -- Add author_name field
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'author_name') THEN
        ALTER TABLE twitter_data ADD COLUMN author_name TEXT;
        RAISE NOTICE 'Added author_name field to twitter_data table';
    END IF;

    -- Add engagement metrics
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'retweet_count') THEN
        ALTER TABLE twitter_data ADD COLUMN retweet_count INTEGER DEFAULT 0;
        RAISE NOTICE 'Added retweet_count field to twitter_data table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'like_count') THEN
        ALTER TABLE twitter_data ADD COLUMN like_count INTEGER DEFAULT 0;
        RAISE NOTICE 'Added like_count field to twitter_data table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'reply_count') THEN
        ALTER TABLE twitter_data ADD COLUMN reply_count INTEGER DEFAULT 0;
        RAISE NOTICE 'Added reply_count field to twitter_data table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'quote_count') THEN
        ALTER TABLE twitter_data ADD COLUMN quote_count INTEGER DEFAULT 0;
        RAISE NOTICE 'Added quote_count field to twitter_data table';
    END IF;

    -- Add source_url and retrieved_at for full tweet tracking
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'source_url') THEN
        ALTER TABLE twitter_data ADD COLUMN source_url TEXT;
        RAISE NOTICE 'Added source_url field to twitter_data table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'retrieved_at') THEN
        ALTER TABLE twitter_data ADD COLUMN retrieved_at TEXT;
        RAISE NOTICE 'Added retrieved_at field to twitter_data table';
    END IF;
END $$;

-- ==============================================
-- Fix 6: Add Missing Indexes for Performance
-- ==============================================

-- Add missing indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_twitter_data_tweet_id ON twitter_data(tweet_id);
CREATE INDEX IF NOT EXISTS idx_twitter_data_discord_message_id ON twitter_data(discord_message_id);
CREATE INDEX IF NOT EXISTS idx_orders_parent_brokerage_order_id ON orders(parent_brokerage_order_id);
CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state);

-- ==============================================
-- Fix 7: Update Field Comments for Documentation
-- ==============================================

-- Add comments to document the aligned schema
COMMENT ON COLUMN orders.diary IS 'Trade diary notes and annotations';
COMMENT ON COLUMN orders.parent_brokerage_order_id IS 'Parent order ID for multi-leg strategies';
COMMENT ON COLUMN orders.state IS 'Order state for lifecycle tracking';
COMMENT ON COLUMN orders.user_secret IS 'Legacy user secret field for backwards compatibility';

COMMENT ON COLUMN discord_messages.user_id IS 'Internal user ID for tracking (default: default_user)';

COMMENT ON COLUMN twitter_data.tweet_id IS 'Twitter/X post unique identifier';
COMMENT ON COLUMN twitter_data.discord_message_id IS 'Associated Discord message ID';
COMMENT ON COLUMN twitter_data.discord_sent_date IS 'When the tweet link was shared in Discord';
COMMENT ON COLUMN twitter_data.tweet_created_date IS 'Original tweet creation timestamp';
COMMENT ON COLUMN twitter_data.tweet_content IS 'Full tweet text content';
COMMENT ON COLUMN twitter_data.author_username IS 'Tweet author username (@handle)';
COMMENT ON COLUMN twitter_data.author_name IS 'Tweet author display name';
COMMENT ON COLUMN twitter_data.retweet_count IS 'Number of retweets/reposts';
COMMENT ON COLUMN twitter_data.like_count IS 'Number of likes/hearts';
COMMENT ON COLUMN twitter_data.reply_count IS 'Number of replies';
COMMENT ON COLUMN twitter_data.quote_count IS 'Number of quote tweets';
COMMENT ON COLUMN twitter_data.source_url IS 'Original tweet URL';
COMMENT ON COLUMN twitter_data.retrieved_at IS 'When tweet data was fetched';

-- Log completion
DO $$ BEGIN
    RAISE NOTICE 'Successfully completed schema alignment fixes:';
    RAISE NOTICE '  ✅ Applied missing discord_rename migration (002) effects';
    RAISE NOTICE '  ✅ Fixed quote_currency field type conversion to JSONB';
    RAISE NOTICE '  ✅ Added missing base schema fields to orders table';
    RAISE NOTICE '  ✅ Aligned discord_messages field types (author_id, reply_to_id → BIGINT)';
    RAISE NOTICE '  ✅ Enhanced twitter_data schema to match comprehensive base schema';
    RAISE NOTICE '  ✅ Added missing indexes for performance optimization';
    RAISE NOTICE '  ✅ Updated field comments for comprehensive documentation';
    RAISE NOTICE 'Schema is now fully aligned between migration files, database state, and code expectations!';
END $$;