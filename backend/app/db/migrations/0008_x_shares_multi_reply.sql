-- Allow the same article to be posted as replies to different X posts
-- (multi-link craft / Open-in-X queue). Standalone posts remain unique per article.

DROP INDEX IF EXISTS idx_x_article_shares_posted_once;

UPDATE x_article_shares
SET reply_to_post_id = ''
WHERE reply_to_post_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_x_article_shares_posted_once
  ON x_article_shares (article_id, reply_to_post_id)
  WHERE status = 'posted';
