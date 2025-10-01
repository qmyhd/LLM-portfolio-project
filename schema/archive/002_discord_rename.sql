-- Idempotent rename + uniqueness + legacy constraint rename guards

DO $$
BEGIN
  IF to_regclass('public.discord_market_clean') IS NULL
     AND to_regclass('public.discord_general_clean') IS NOT NULL THEN
    EXECUTE 'ALTER TABLE public.discord_general_clean RENAME TO discord_market_clean';
  END IF;
END$$;

-- Rename old constraint names if they carried over from the old table name
DO $$
BEGIN
  IF to_regclass('public.discord_market_clean') IS NOT NULL THEN
    IF EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conname = 'discord_general_clean_message_id_key'
        AND conrelid = 'public.discord_market_clean'::regclass
    ) THEN
      EXECUTE 'ALTER TABLE public.discord_market_clean
               RENAME CONSTRAINT discord_general_clean_message_id_key
               TO discord_market_clean_message_id_key';
    END IF;

    IF EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conname = 'discord_general_clean_pkey'
        AND conrelid = 'public.discord_market_clean'::regclass
    ) THEN
      EXECUTE 'ALTER TABLE public.discord_market_clean
               RENAME CONSTRAINT discord_general_clean_pkey
               TO discord_market_clean_pkey';
    END IF;
  END IF;
END$$;

-- Ensure uniqueness (safe on rerun)
CREATE UNIQUE INDEX IF NOT EXISTS discord_market_clean_msgid_uq
  ON public.discord_market_clean(message_id);

CREATE UNIQUE INDEX IF NOT EXISTS discord_trading_clean_msgid_uq
  ON public.discord_trading_clean(message_id);
