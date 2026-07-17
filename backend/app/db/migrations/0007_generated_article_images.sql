ALTER TABLE generated_articles
  ADD COLUMN IF NOT EXISTS image TEXT DEFAULT '{}';
