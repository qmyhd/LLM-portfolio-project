-- Migration 035: Add chunk segmentation fields
-- Adds section-aware chunking metadata to discord_message_chunks

-- Add section_title column
ALTER TABLE discord_message_chunks 
ADD COLUMN IF NOT EXISTS section_title TEXT;

-- Add section_type column (enum-like: headings, orders, watchlist, technical_analysis, portfolio, chat, command, other)
ALTER TABLE discord_message_chunks 
ADD COLUMN IF NOT EXISTS section_type TEXT;

-- Add idea_index column (index of the idea unit within a section)
ALTER TABLE discord_message_chunks 
ADD COLUMN IF NOT EXISTS idea_index INTEGER;

-- Create index on section_type for filtering
CREATE INDEX IF NOT EXISTS idx_chunks_section_type 
ON discord_message_chunks(section_type);

-- Create composite index for section-based queries
CREATE INDEX IF NOT EXISTS idx_chunks_section_title_type 
ON discord_message_chunks(section_title, section_type);

COMMENT ON COLUMN discord_message_chunks.section_title IS 'Title of the document section this chunk belongs to';
COMMENT ON COLUMN discord_message_chunks.section_type IS 'Type of section: headings, orders, watchlist, technical_analysis, portfolio, chat, command, other';
COMMENT ON COLUMN discord_message_chunks.idea_index IS 'Index of the idea unit within the section (0-based)';
