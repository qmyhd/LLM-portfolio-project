-- Migration 026: Add media_urls column to twitter_data table
-- Stores JSON array of media attachments (images, videos, GIFs) from tweets

ALTER TABLE twitter_data 
ADD COLUMN IF NOT EXISTS media_urls JSONB DEFAULT '[]'::jsonb;

-- Add comment for documentation
COMMENT ON COLUMN twitter_data.media_urls IS 'JSON array of media attachments: [{url, type, alt_text}]';

-- Create index for efficient querying of tweets with media
CREATE INDEX IF NOT EXISTS idx_twitter_data_has_media 
ON twitter_data ((media_urls != '[]'::jsonb));
