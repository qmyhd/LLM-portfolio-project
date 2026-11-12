-- =======================================================================
-- Migration 080: Four roles (pending/guest/family/owner) and password accounts
-- =======================================================================
-- Replaces the owner/editor/viewer roles with pending/guest/family/owner and
-- adds the columns username+password sign-in needs. Existing non-owner users
-- become 'pending' until an owner approves them. Safe to run twice.

-- 1. Drop any CHECK on app_users that mentions role (the original inline
--    constraint is app_users_role_check, but look it up rather than assume).
--    This must come before the data update: the old CHECK rejects 'pending'.
DO $$
DECLARE
    con RECORD;
BEGIN
    FOR con IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.conrelid = 'public.app_users'::regclass
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%role%'
    LOOP
        EXECUTE format('ALTER TABLE public.app_users DROP CONSTRAINT %I', con.conname);
    END LOOP;
END $$;

-- 2. Move legacy roles (viewer, editor) to pending. Owners and any row
--    already on a new role are left alone, so a re-run changes nothing.
UPDATE public.app_users
SET role = 'pending'
WHERE role NOT IN ('pending', 'guest', 'family', 'owner');

-- 3. Add the new CHECK and default.
ALTER TABLE public.app_users
    ADD CONSTRAINT app_users_role_check
    CHECK (role IN ('pending', 'guest', 'family', 'owner'));

ALTER TABLE public.app_users
    ALTER COLUMN role SET DEFAULT 'pending';

-- 4. Allow password accounts. Drop any CHECK on provider (original inline
--    constraint is app_users_provider_check), then allow google and password.
DO $$
DECLARE
    con RECORD;
BEGIN
    FOR con IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.conrelid = 'public.app_users'::regclass
          AND c.contype = 'c'
          AND pg_get_constraintdef(c.oid) ILIKE '%provider%'
    LOOP
        EXECUTE format('ALTER TABLE public.app_users DROP CONSTRAINT %I', con.conname);
    END LOOP;
END $$;

ALTER TABLE public.app_users
    ADD CONSTRAINT app_users_provider_check
    CHECK (provider IN ('google', 'password'));

-- email stays NOT NULL UNIQUE: password accounts store '<username>@local' as
-- their email, which keeps it unique.

-- 5. Password-account columns.
ALTER TABLE public.app_users
    ADD COLUMN IF NOT EXISTS password_hash text NULL;
ALTER TABLE public.app_users
    ADD COLUMN IF NOT EXISTS failed_login_count integer NOT NULL DEFAULT 0;
ALTER TABLE public.app_users
    ADD COLUMN IF NOT EXISTS locked_until timestamptz NULL;

INSERT INTO public.schema_migrations (version, description)
VALUES ('080_roles_and_password_accounts',
        'app_users roles pending/guest/family/owner; password_hash, failed_login_count, locked_until')
ON CONFLICT (version) DO NOTHING;
