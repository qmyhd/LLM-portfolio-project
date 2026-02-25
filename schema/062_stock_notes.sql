-- =======================================================================
-- Migration 062: Add stock_notes table for personal annotations
-- =======================================================================

CREATE TABLE IF NOT EXISTS public.stock_notes (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(20) NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast lookups by symbol
CREATE INDEX IF NOT EXISTS idx_stock_notes_symbol
    ON public.stock_notes (UPPER(symbol));

-- Index for ordering by creation date
CREATE INDEX IF NOT EXISTS idx_stock_notes_created_at
    ON public.stock_notes (created_at DESC);

-- Auto-update updated_at on row modification
CREATE OR REPLACE FUNCTION public.update_stock_notes_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS stock_notes_updated_at ON public.stock_notes;
CREATE TRIGGER stock_notes_updated_at
    BEFORE UPDATE ON public.stock_notes
    FOR EACH ROW
    EXECUTE FUNCTION public.update_stock_notes_updated_at();

-- Enable Row Level Security (project standard)
ALTER TABLE public.stock_notes ENABLE ROW LEVEL SECURITY;
