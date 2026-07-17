CREATE TABLE IF NOT EXISTS sources (
  id SERIAL PRIMARY KEY,
  source_name TEXT NOT NULL UNIQUE,
  domain TEXT DEFAULT '',
  country TEXT DEFAULT '',
  language TEXT DEFAULT 'en',
  source_type TEXT DEFAULT 'news',
  reliability_tier TEXT DEFAULT 'standard',
  political_lean_optional TEXT DEFAULT '',
  rss_url TEXT DEFAULT '',
  is_active SMALLINT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS articles (
  id SERIAL PRIMARY KEY,
  source_id INTEGER REFERENCES sources(id),
  source_name TEXT NOT NULL,
  title TEXT NOT NULL,
  normalized_title TEXT,
  url TEXT NOT NULL UNIQUE,
  published_at TEXT,
  description TEXT DEFAULT '',
  raw_text TEXT NOT NULL,
  clean_text TEXT,
  topic TEXT DEFAULT '',
  language TEXT DEFAULT 'en',
  status TEXT DEFAULT 'new',
  duplicate_of INTEGER REFERENCES articles(id),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS entities (
  id SERIAL PRIMARY KEY,
  article_id INTEGER NOT NULL REFERENCES articles(id),
  entity_text TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  start_char INTEGER DEFAULT 0,
  end_char INTEGER DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS claims (
  id SERIAL PRIMARY KEY,
  article_id INTEGER NOT NULL REFERENCES articles(id),
  claim_text TEXT NOT NULL,
  claim_type TEXT DEFAULT 'event',
  entities TEXT DEFAULT '[]',
  source_name TEXT,
  claim_order INTEGER NOT NULL,
  confidence_score REAL DEFAULT 0.75,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS story_clusters (
  id SERIAL PRIMARY KEY,
  topic_label TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS story_cluster_articles (
  id SERIAL PRIMARY KEY,
  story_cluster_id INTEGER NOT NULL REFERENCES story_clusters(id),
  article_id INTEGER NOT NULL REFERENCES articles(id),
  UNIQUE(story_cluster_id, article_id)
);

CREATE TABLE IF NOT EXISTS consensus_claims (
  id SERIAL PRIMARY KEY,
  story_cluster_id INTEGER NOT NULL REFERENCES story_clusters(id),
  claim_text TEXT NOT NULL,
  support_count INTEGER NOT NULL,
  source_list TEXT NOT NULL,
  status TEXT NOT NULL,
  source_diversity_score REAL DEFAULT 0,
  confidence_score REAL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS generated_summaries (
  id SERIAL PRIMARY KEY,
  story_cluster_id INTEGER NOT NULL REFERENCES story_clusters(id),
  summary_text TEXT NOT NULL,
  model_name TEXT NOT NULL,
  version INTEGER DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS generated_articles (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  tag TEXT DEFAULT 'trend',
  trend_url TEXT DEFAULT '',
  prompt TEXT NOT NULL,
  headline TEXT NOT NULL,
  dek TEXT NOT NULL,
  summary TEXT NOT NULL,
  body TEXT NOT NULL,
  facts TEXT NOT NULL,
  terms TEXT NOT NULL,
  sources TEXT NOT NULL,
  source_links TEXT DEFAULT '[]',
  consensus TEXT DEFAULT '[]',
  source_count INTEGER NOT NULL,
  denied_for_bias INTEGER NOT NULL,
  fairness_score INTEGER NOT NULL,
  accuracy_score INTEGER NOT NULL,
  score_metadata TEXT DEFAULT '{}',
  generation_mode TEXT DEFAULT '',
  source_quality TEXT DEFAULT '{}',
  consensus_level TEXT DEFAULT '',
  used_live_sources SMALLINT DEFAULT 0,
  fallback_reason TEXT DEFAULT '',
  section TEXT DEFAULT '',
  status TEXT DEFAULT 'published',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS x_article_shares (
  id BIGSERIAL PRIMARY KEY,
  article_id TEXT NOT NULL REFERENCES generated_articles(id) ON DELETE CASCADE,
  draft_text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('posted', 'dry_run', 'failed')),
  x_post_id TEXT DEFAULT '',
  x_post_url TEXT DEFAULT '',
  reply_to_post_id TEXT DEFAULT '',
  reply_url TEXT DEFAULT '',
  error TEXT DEFAULT '',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS article_likes (
  id SERIAL PRIMARY KEY,
  article_id TEXT NOT NULL REFERENCES generated_articles(id) ON DELETE CASCADE,
  user_id INTEGER,
  session_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(article_id, user_id),
  UNIQUE(article_id, session_id)
);

CREATE TABLE IF NOT EXISTS article_comments (
  id SERIAL PRIMARY KEY,
  article_id TEXT NOT NULL REFERENCES generated_articles(id) ON DELETE CASCADE,
  user_id INTEGER,
  session_id TEXT DEFAULT '',
  author_name TEXT DEFAULT 'Reader',
  body TEXT NOT NULL,
  parent_comment_id INTEGER REFERENCES article_comments(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comment_likes (
  id SERIAL PRIMARY KEY,
  comment_id INTEGER NOT NULL REFERENCES article_comments(id) ON DELETE CASCADE,
  user_id INTEGER,
  session_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(comment_id, user_id),
  UNIQUE(comment_id, session_id)
);

CREATE TABLE IF NOT EXISTS notifications (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL,
  type TEXT NOT NULL,
  article_id TEXT REFERENCES generated_articles(id) ON DELETE CASCADE,
  comment_id INTEGER REFERENCES article_comments(id) ON DELETE CASCADE,
  actor_user_id INTEGER,
  actor_name TEXT DEFAULT 'Reader',
  message TEXT NOT NULL,
  is_read SMALLINT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  plan TEXT DEFAULT 'Reader',
  role TEXT NOT NULL DEFAULT 'reader',
  supabase_user_id UUID UNIQUE,
  email_confirmed SMALLINT NOT NULL DEFAULT 0,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT users_role_check CHECK (role IN ('reader', 'editor', 'admin'))
);

CREATE TABLE IF NOT EXISTS user_preferences (
  id SERIAL PRIMARY KEY,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
  region TEXT DEFAULT 'Global',
  edition TEXT DEFAULT 'Morning',
  density TEXT DEFAULT 'Comfortable',
  source_threshold INTEGER DEFAULT 8,
  email_alerts SMALLINT DEFAULT 1,
  show_disputed_claims SMALLINT DEFAULT 1,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE generated_articles
  ADD COLUMN IF NOT EXISTS owner_user_id INTEGER REFERENCES users(id);

CREATE TABLE IF NOT EXISTS saved_stories (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  story_id TEXT NOT NULL,
  title TEXT NOT NULL,
  source_count INTEGER DEFAULT 0,
  saved_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_history (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  session_id TEXT,
  action_type TEXT NOT NULL,
  topic TEXT,
  section TEXT,
  prompt TEXT,
  article_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_name);
CREATE INDEX IF NOT EXISTS idx_articles_normalized_title ON articles(normalized_title);
CREATE INDEX IF NOT EXISTS idx_sources_name ON sources(source_name);
CREATE INDEX IF NOT EXISTS idx_sources_active ON sources(is_active);
CREATE INDEX IF NOT EXISTS idx_entities_text ON entities(entity_text);
CREATE INDEX IF NOT EXISTS idx_claims_article ON claims(article_id);
CREATE INDEX IF NOT EXISTS idx_consensus_cluster ON consensus_claims(story_cluster_id);
CREATE INDEX IF NOT EXISTS idx_generated_articles_created ON generated_articles(created_at);
CREATE INDEX IF NOT EXISTS idx_generated_articles_owner ON generated_articles(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_generated_articles_source ON generated_articles(source);
CREATE INDEX IF NOT EXISTS idx_x_article_shares_article_created
  ON x_article_shares(article_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_x_article_shares_posted_once
  ON x_article_shares(article_id) WHERE status = 'posted';
CREATE INDEX IF NOT EXISTS idx_saved_stories_user ON saved_stories(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_stories_unique_user_story ON saved_stories(user_id, story_id);
CREATE INDEX IF NOT EXISTS idx_user_history_user ON user_history(user_id);
CREATE INDEX IF NOT EXISTS idx_user_history_session ON user_history(session_id);
CREATE INDEX IF NOT EXISTS idx_user_history_action ON user_history(action_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_article_likes_article ON article_likes(article_id);
CREATE INDEX IF NOT EXISTS idx_article_comments_article ON article_comments(article_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comment_likes_comment ON comment_likes(comment_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read, created_at DESC);
