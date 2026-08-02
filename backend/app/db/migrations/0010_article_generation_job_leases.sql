-- Durable claim leases for article-generation jobs.
-- Workers stamp claimed_at when they take a job; jobs whose worker died are
-- automatically returned to a safe durable state by the queue-maintenance
-- pass instead of staying stuck in 'sourcing'/'generating' forever.

ALTER TABLE article_generation_jobs
  ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_article_generation_jobs_ready
  ON article_generation_jobs(priority DESC, created_at ASC)
  WHERE status = 'ready_for_generation';

CREATE INDEX IF NOT EXISTS idx_article_generation_jobs_inflight
  ON article_generation_jobs(claimed_at)
  WHERE status IN ('sourcing', 'generating');

-- One-time rescue: jobs interrupted before lease recovery existed have no
-- worker and would otherwise remain stuck until manual intervention.
UPDATE article_generation_jobs
SET status = CASE WHEN status = 'generating' THEN 'ready_for_generation' ELSE 'queued' END,
    error = ''
WHERE status IN ('sourcing', 'generating');
