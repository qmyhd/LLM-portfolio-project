-- Migration: Add notified column to orders table
-- Purpose: Track which orders have had Discord notifications sent
-- Created: 2026-01-26

-- Add notified column with default false
ALTER TABLE orders 
ADD COLUMN IF NOT EXISTS notified BOOLEAN DEFAULT false;

-- Add index for finding unnotified orders
CREATE INDEX IF NOT EXISTS idx_orders_notified 
ON orders (notified, status) 
WHERE status = 'filled' AND notified = false;

-- Comment on the column
COMMENT ON COLUMN orders.notified IS 'Whether a Discord notification has been sent for this filled order';
