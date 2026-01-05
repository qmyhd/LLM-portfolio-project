-- Migration: Add raw_symbol column to positions table
-- Description: Adds raw_symbol column to store the original symbol from the brokerage
-- Created: 2025-12-08

ALTER TABLE positions ADD COLUMN IF NOT EXISTS raw_symbol TEXT;
