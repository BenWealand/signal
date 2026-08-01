CREATE INDEX IF NOT EXISTS idx_articles_created_at_desc
  ON articles(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_entities_text_lower
  ON entities(LOWER(entity_text));

CREATE INDEX IF NOT EXISTS idx_articles_search_fts
  ON articles USING GIN (
    (
      setweight(to_tsvector('english'::regconfig, COALESCE(title, '')), 'A') ||
      setweight(to_tsvector('english'::regconfig, COALESCE(description, '')), 'B') ||
      setweight(to_tsvector('english'::regconfig, COALESCE(topic, '')), 'B') ||
      setweight(to_tsvector('english'::regconfig, COALESCE(clean_text, '')), 'C')
    )
  );
