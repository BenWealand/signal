CREATE INDEX IF NOT EXISTS idx_generated_articles_created_at_desc
  ON generated_articles (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_story_clusters_updated_at_desc
  ON story_clusters (updated_at DESC);
