-- Allow anonymous/authenticated clients to read published articles via Supabase
-- PostgREST (bypasses the Render API cold start for /article/:id shares).

GRANT USAGE ON SCHEMA public TO anon, authenticated;
GRANT SELECT ON TABLE generated_articles TO anon, authenticated;

ALTER TABLE generated_articles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS generated_articles_public_read ON generated_articles;

CREATE POLICY generated_articles_public_read
  ON generated_articles
  FOR SELECT
  TO anon, authenticated
  USING (
    COALESCE(status, 'published') IN ('published', 'public', '')
  );
