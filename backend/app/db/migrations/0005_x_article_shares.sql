CREATE TABLE IF NOT EXISTS x_article_shares (
  id BIGSERIAL PRIMARY KEY,
  article_id TEXT NOT NULL REFERENCES generated_articles(id) ON DELETE CASCADE,
  draft_text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('posted', 'dry_run', 'failed')),
  x_post_id TEXT DEFAULT '',
  x_post_url TEXT DEFAULT '',
  error TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_x_article_shares_article_created
  ON x_article_shares(article_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_x_article_shares_posted_once
  ON x_article_shares(article_id) WHERE status = 'posted';
