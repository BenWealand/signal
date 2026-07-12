-- User auth/permissions extensions (roles stay app-side; passwords stay in Supabase Auth).
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'reader';

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS email_confirmed SMALLINT NOT NULL DEFAULT 0;

UPDATE users
SET role = 'reader'
WHERE role IS NULL OR role = '';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'users_role_check'
  ) THEN
    ALTER TABLE users
      ADD CONSTRAINT users_role_check
      CHECK (role IN ('reader', 'editor', 'admin'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
CREATE INDEX IF NOT EXISTS idx_users_email_lower ON users (LOWER(email));
