ALTER TABLE generated_articles
  ADD COLUMN IF NOT EXISTS source_fingerprint TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_generated_articles_source_fingerprint
  ON generated_articles(source_fingerprint, created_at DESC)
  WHERE source_fingerprint <> '';

CREATE TABLE IF NOT EXISTS article_generation_jobs (
  id TEXT PRIMARY KEY,
  prompt TEXT NOT NULL,
  normalized_prompt TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('fast', 'thorough')),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'sourcing', 'ready_for_generation', 'generating', 'saved', 'failed')),
  priority INTEGER NOT NULL DEFAULT 0,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  article_id TEXT REFERENCES generated_articles(id) ON DELETE SET NULL,
  error TEXT DEFAULT '',
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_article_generation_jobs_queue
  ON article_generation_jobs(priority DESC, created_at ASC)
  WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_article_generation_jobs_prompt
  ON article_generation_jobs(normalized_prompt, finished_at DESC);
