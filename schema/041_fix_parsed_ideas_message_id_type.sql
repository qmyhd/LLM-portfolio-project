-- Migration 041: Fix discord_parsed_ideas.message_id type to match discord_messages
-- Also add foreign key constraint and sensible defaults

-- Step 1: Drop the unique constraint that depends on message_id
ALTER TABLE discord_parsed_ideas 
DROP CONSTRAINT IF EXISTS discord_parsed_ideas_message_id_idea_index_key;

-- Step 2: Change message_id from BIGINT to TEXT
ALTER TABLE discord_parsed_ideas 
ALTER COLUMN message_id TYPE TEXT USING message_id::TEXT;

-- Step 3: Recreate the unique constraint
ALTER TABLE discord_parsed_ideas 
ADD CONSTRAINT discord_parsed_ideas_message_id_idea_index_key 
UNIQUE (message_id, idea_index);

-- Step 4: Add foreign key to discord_messages
ALTER TABLE discord_parsed_ideas 
ADD CONSTRAINT fk_discord_parsed_ideas_message 
FOREIGN KEY (message_id) 
REFERENCES discord_messages(message_id) 
ON DELETE CASCADE;

-- Step 5: Add sensible defaults to NOT NULL columns without defaults
-- prompt_version defaults to 'unknown' 
ALTER TABLE discord_parsed_ideas 
ALTER COLUMN prompt_version SET DEFAULT 'unknown';

-- model defaults to 'unknown'
ALTER TABLE discord_parsed_ideas 
ALTER COLUMN model SET DEFAULT 'unknown';

-- Add index on foreign key for better join performance
CREATE INDEX IF NOT EXISTS idx_discord_parsed_ideas_message_id 
ON discord_parsed_ideas(message_id);

-- Add comment explaining the relationship
COMMENT ON CONSTRAINT fk_discord_parsed_ideas_message ON discord_parsed_ideas 
IS 'Links parsed ideas to their source Discord message';
