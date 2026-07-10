# Signal Backend

FastAPI backend for Signal Dispatch, the source-transparent news intelligence prototype.

## Important Database Note

The current backend requires **PostgreSQL**. It uses `psycopg2`, PostgreSQL SQL features, and the schema in `app/db/schema.sql`.

The file `backend/signal_news.db` is a legacy/demo artifact from an older SQLite direction. The current application does not read it. Unless a SQLite adapter is added later, use PostgreSQL or Supabase Postgres.

## Quick Start

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-core.txt
python scripts/create_tables.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

macOS/Linux activation:

```bash
source .venv/bin/activate
```

## Dependency Files

- `requirements-core.txt`: minimal backend runtime for API, PostgreSQL, article extraction, and provider clients.
- `requirements-ml.txt`: optional spaCy and sentence-transformer stack for stronger NER and semantic claim grouping.
- `requirements-dev.txt`: developer/test layer. Current tests use standard-library `unittest`.
- `requirements.txt`: default hosted/free-tier install. It includes only `requirements-core.txt`.
- `requirements-full.txt`: all-in local/demo install with optional ML/dev dependencies.

Recommended local path:

```bash
pip install -r requirements-core.txt
```

Optional ML install:

```bash
pip install -r requirements-full.txt
```

## Render Free Tier

Render free web services have tight memory limits. Use the default `requirements.txt`
and keep startup background work disabled unless you move to a larger instance:

```env
SIGNAL_AUTO_INGEST_ON_STARTUP=false
SIGNAL_PERIODIC_RSS=false
SIGNAL_EMBEDDING_WARMUP_ON_STARTUP=false
```

All-in:

```bash
pip install -r requirements.txt
```

## Required Environment

Set this in `backend/.env`, root `.env`, or your deployment environment:

```env
DATABASE_URL=postgresql://...
```

Supabase pooled connection strings usually look like:

```env
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
```

Use the connection string for your own Supabase region/project.

## Recommended Environment

```env
PUBLIC_ARTICLE_BASE_URL=http://127.0.0.1:5175
GEMINI_MODEL=gemini-flash-latest
CLAIM_MODEL=gpt-4o-mini
SUMMARY_MODEL=gpt-4o-mini
USE_LLM_CLAIMS=false
PROMPT_BLACKLIST=
PROMPT_BLACKLIST_REGEX=
```

Prompt filtering:

- `PROMPT_BLACKLIST` is a comma- or newline-separated list of blocked words/phrases.
- `PROMPT_BLACKLIST_REGEX` is a comma- or newline-separated list of case-insensitive regex patterns.
- Matching prompts return `422 prompt_blocked`.
- Matching generated articles are purged on backend startup and hidden from generated/trending/section lists.
- To purge immediately after changing Render env vars, call `POST /generated-articles/purge-blocked` with `X-Signal-Token` or `Authorization: Bearer ...`.

## Optional Provider Keys

```env
GEMINI_API_KEY=
OPENAI_API_KEY=
NEWS_API_KEY=
CURRENTS_API_KEY=
GNEWS_API_KEY=
GUARDIAN_CONTENT_API_KEY=
GOOGLE_FACT_CHECK_API_KEY=
RSS_FEEDS=
GDELT_QUERIES=
```

Behavior:

- No Gemini key: generated article writes fail without saving an article.
- Gemini rate limit/API failure: generated article writes fail without saving an article.
- No OpenAI key: local claim extraction is used.
- `USE_LLM_CLAIMS=false`: OpenAI is not used for claim extraction.
- No paid/news provider keys: RSS, Bing News RSS, and GDELT still provide candidates.

## Agent / X Integration

Protected agent endpoints require:

```env
SIGNAL_API_TOKEN=replace-with-a-long-random-token
PUBLIC_ARTICLE_BASE_URL=https://your-frontend.example
```

Send the token as either:

```text
X-Signal-Token: your-token
Authorization: Bearer your-token
```

## Database Setup

Create tables:

```bash
python scripts/create_tables.py
```

Optional seed/sample pipeline:

```bash
python scripts/seed_sources.py
python scripts/load_sample_articles.py
python scripts/run_pipeline.py
```

Optional ingest scripts:

```bash
python scripts/fetch_rss.py
python scripts/fetch_gdelt.py
python scripts/rss_stats.py
```

`fetch_rss.py` uses configured `RSS_FEEDS`. Prompt-based article writing does not need predefined `GDELT_QUERIES`; the submitted prompt becomes the live query.

## Run The API

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
```

## Main Endpoints

```text
GET /health
GET /stories
GET /stories/latest
GET /stories/trending
GET /stories/{story_id}
GET /stories/{story_id}/claims
GET /stories/{story_id}/consensus
GET /articles/progress
GET /articles/{article_id}
GET /articles/source/{source_name}
GET /sources
GET /generated-articles
GET /generated-articles/{article_id}
POST /articles/generate-from-trend
POST /agents/x/article-reply
POST /articles/write
GET /news/{section}
POST /news/refresh/{section}
GET /news/trending-topics
POST /ingest/rss
POST /ingest/rss/{section}
GET /ingest/rss/status
GET /search?q=...
GET /entities/{entity_name}
POST /users
POST /history
POST /saved-stories
```

## Prompt Article Payload

```json
{
  "prompt": "any article topic the reader enters",
  "limit": 12,
  "mode": "fast"
}
```

Modes:

- `fast`: lower latency, uses current source snippets/candidates, intended for UI responsiveness.
- `thorough`: runs more enrichment, processing, claim extraction, clustering, consensus, and synthesis work.

Prompt article responses include source-transparency metadata:

- `generation_mode`: `fast` or `thorough`.
- `source_quality`: usable source count, domain diversity, text-length gates, recency requirements, ranking/rejection details when available.
- `consensus_level`: `none`, `limited`, `moderate`, `strong`, or `conflicting`.
- `used_live_sources`: whether live RSS/GDELT/API candidates were used.
- `fallback_reason`: legacy metadata on older generated articles. New prompt/section generation does not save fallback articles.
- `scoreMetadata`: explains that legacy `fairnessScore` and `accuracyScore` are heuristic estimates, not audited ratings.

The frontend currently sends `mode: "fast"` for prompt writes.

## X Agent Reply Payload

```json
{
  "trending_topic": "#ExampleTrend",
  "snippet": "A short excerpt from a public X post or trending topic context.",
  "trend_url": "https://x.com/...",
  "mode": "fast"
}
```

`POST /agents/x/article-reply` returns:

- `article`
- `articleUrl`
- `replyText`
- `status`
- `trendUrl`

## Cheapest Accurate Pipeline

Signal is wired to spend money late:

1. Discover article candidates with RSS, Bing News RSS, GDELT, and optional APIs.
2. Store metadata and source information.
3. Deduplicate by URL, normalized title, source, and title similarity.
4. Clean article text.
5. Extract entities with spaCy when installed or a fallback otherwise.
6. Extract claims with local rules by default.
7. Optionally enable LLM claim extraction with `USE_LLM_CLAIMS=true`.
8. Compare claims locally first.
9. Use Gemini for final prose.
10. Fail the write without saving an article when Gemini cannot produce a usable draft.

## Tests

```bash
cd backend
python -m unittest discover tests
```

The existing test suite covers agent access, article parsing, source ranking/filtering, prompt article metadata, Gemini-only prompt writes, claim extraction, text cleaning, and consensus grouping.

## Troubleshooting

`psycopg2.OperationalError` on startup

Check `DATABASE_URL`, password, database host, port, `sslmode=require`, and whether your provider allows connections from your machine/server.

`GET /health` reports database `ok: false`

The API started, but startup table creation failed. Check backend logs and database connectivity.

Article generation finds too few sources

Try a more specific prompt, add optional provider keys, or wait for RSS/GDELT availability. The writer now fails without saving an article when source coverage is not strong enough for a Gemini draft.

Gemini does not write articles

Check `GEMINI_API_KEY`, `GEMINI_MODEL`, `/articles/test-gemini`, and rate limits. Prompt and section article generation now require a usable Gemini draft.

ML packages are slow or fail to install

Use `requirements-core.txt` first. Install `requirements-ml.txt` only when you need semantic similarity and heavier NLP.
