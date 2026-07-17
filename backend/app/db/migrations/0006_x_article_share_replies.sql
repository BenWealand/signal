ALTER TABLE x_article_shares
  ADD COLUMN IF NOT EXISTS reply_to_post_id TEXT DEFAULT '';

ALTER TABLE x_article_shares
  ADD COLUMN IF NOT EXISTS reply_url TEXT DEFAULT '';
