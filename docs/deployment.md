# Deployment Guide

Signal Dispatch is split into a static/Vite frontend and a FastAPI backend. Deploy them as separate services unless you deliberately add a combined container later.

## Recommended Deployment Shape

- Frontend: Vercel static/Vite deployment.
- Backend: Render, Fly.io, Railway, or another Python web service.
- Database: Supabase Postgres.
- Optional auth: Supabase Auth in the frontend.
- Optional LLM/news keys: configured only on the backend service.

Do not put backend provider secrets into Vercel frontend variables unless the variable starts with `VITE_` and is safe to expose publicly.

## Supabase Postgres

1. Create a Supabase project.
2. Go to Project Settings -> Database.
3. Copy the Postgres connection string.
4. Prefer a pooled connection string for serverless-ish hosts.
5. Add `sslmode=require` when required by the connection string or hosting provider.
6. Set that value as `DATABASE_URL` on the backend host.
7. Run the backend migration command once:

```bash
cd backend
python scripts/create_tables.py
```

The schema is in `backend/app/db/schema.sql`. It uses PostgreSQL features and is not SQLite-compatible.

## Vercel Frontend

Build settings:

```text
Framework preset: Vite
Build command: npm run build
Output directory: dist
Install command: npm install
```

Frontend environment variables:

```env
VITE_SIGNAL_API_URL=https://your-backend.example.com
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=your-public-anon-key
```

Only `VITE_*` variables are exposed to the frontend. Do not add `DATABASE_URL`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, or news provider keys to the frontend project.

The repo includes `vercel.json` with a single-page-app rewrite so direct links like `/?article=...` and future client routes fall back to `index.html`.

Static fallback behavior:

- The frontend attempts to load `GET /feeds/bootstrap` from the backend (one request for Latest, Trending, topics, and all section feeds).
- It also loads `/generated-articles.json` from the static build.
- If the backend is unavailable, the UI can show cached feed data. Local preview drafts are only used when the frontend is intentionally built without `VITE_SIGNAL_API_URL`.
- Backend-configured deployments should not present local/demo drafts as generated articles.

## Backend keep-alive (recommended)

If the backend host sleeps after inactivity (Render free tier, etc.), configure a scheduled ping so the first reader does not wait through a cold start:

1. In GitHub → Settings → Secrets and variables → Actions, add `SIGNAL_API_URL` with your backend base URL (no trailing slash), e.g. `https://your-backend.onrender.com`.
2. The workflow at `.github/workflows/keep-backend-alive.yml` pings `/awake` every 5 minutes.

Alternative: use UptimeRobot, Cron-job.org, or a Vercel cron job pointed at the same `/awake` URL.

## Feed performance settings

Optional backend environment variables:

```env
DB_POOL_MAX=8
FEED_CACHE_TTL_SECONDS=60
GEMINI_FAST_MODEL=gemini-flash-lite-latest
SIGNAL_FAST_CACHE_MIN_SOURCES=4
SIGNAL_THOROUGH_ENRICH_LIMIT=12
SIGNAL_THOROUGH_ENRICH_TIMEOUT=8
SIGNAL_DAILY_INGEST=false
```

What these do:

- `DB_POOL_MAX`: reuses Postgres connections instead of opening a new TLS session per request.
- `FEED_CACHE_TTL_SECONDS`: memoizes trending rankings and the `/feeds/bootstrap` bundle in memory for all visitors.
- `GEMINI_FAST_MODEL`: model used for Fast-mode packaged article writes (headline + dek + body in one call).
- `SIGNAL_FAST_CACHE_MIN_SOURCES`: Fast mode answers from the daily desk cache once this many recent sources match.
- `SIGNAL_THOROUGH_ENRICH_LIMIT` / `TIMEOUT`: cap how many pages Thorough mode scrapes and how long each scrape may take.
- `SIGNAL_DAILY_INGEST`: optional in-process daily RSS refresh. Prefer the GitHub Action `daily-source-ingest.yml` on free-tier hosts.
- List endpoints (`/generated-articles`, `/news/trending`, section pages) return slim card previews; opening an article fetches the full body from `/generated-articles/{id}`.

## Daily desk cache

Fast article writes prefer recently ingested Postgres coverage before live providers.

1. Add repository secrets `SIGNAL_API_URL` and `SIGNAL_API_TOKEN`.
2. The workflow `.github/workflows/daily-source-ingest.yml` wakes the API and posts `POST /ingest/daily` once per day.
3. That endpoint refreshes RSS into Postgres and regenerates shared section drafts.

## Backend On Render

Example settings:

```text
Runtime: Python
Root directory: backend
Build command: pip install -r requirements-core.txt
Start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Backend environment variables:

```env
DATABASE_URL=postgresql://...
GEMINI_API_KEY=...
PUBLIC_ARTICLE_BASE_URL=https://your-frontend.vercel.app
CORS_ORIGINS=https://your-frontend.vercel.app
GEMINI_MODEL=gemini-flash-latest
USE_LLM_CLAIMS=false
SIGNAL_AUTO_INGEST_ON_STARTUP=false
SIGNAL_PERIODIC_RSS=false
SIGNAL_EMBEDDING_WARMUP_ON_STARTUP=false
SIGNAL_SECTION_FAST_COUNT=3
```

Optional:

```env
OPENAI_API_KEY=
NEWS_API_KEY=
CURRENTS_API_KEY=
GNEWS_API_KEY=
GUARDIAN_CONTENT_API_KEY=
SIGNAL_API_TOKEN=
SUPABASE_JWT_SECRET=
```

After first deploy, run:

```bash
python scripts/create_tables.py
```

Use Render shell or a one-off job if available.

## Backend On Railway

Typical setup:

```text
Root directory: backend
Build command: pip install -r requirements-core.txt
Start command: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Set the same backend environment variables as Render.

If using Railway Postgres instead of Supabase, set `DATABASE_URL` to Railway's Postgres URL. The rest of the app does not require Supabase Postgres specifically.

## Backend On Fly.io

This repo does not currently include a `Dockerfile` or `fly.toml`. A practical Fly deployment should add a backend-focused Dockerfile that:

1. Uses a Python base image.
2. Sets workdir to `/app`.
3. Copies `backend/`.
4. Installs `requirements-core.txt`.
5. Runs `uvicorn app.main:app --host 0.0.0.0 --port 8080`.

Use Fly secrets:

```bash
fly secrets set DATABASE_URL="postgresql://..."
fly secrets set PUBLIC_ARTICLE_BASE_URL="https://your-frontend.vercel.app"
fly secrets set GEMINI_API_KEY="..."
```

Expose port `8080` or match your `fly.toml` service configuration.

## CORS

Local CORS origins are enabled by default:

```text
http://127.0.0.1:5175
http://localhost:5175
http://127.0.0.1:5173
http://localhost:5173
http://127.0.0.1:4173
http://localhost:4173
```

Before deploying a real frontend, set `CORS_ORIGINS` on the backend to include the Vercel frontend origin, for example:

CORS_ORIGINS=https://your-frontend.vercel.app,https://your-domain.com
```

Do not include path segments. Origins should be only scheme + host:

```text
https://your-frontend.vercel.app
https://your-domain.com
```

## Can The Backend Run On Vercel Hobby?

Not as-is. Vercel can run Python Functions, but this backend is a long-running FastAPI service with startup ingestion, daemon refresh loops, background jobs, PostgreSQL access, optional article extraction, and potentially slow generation calls. That shape fits a persistent Python web service better than request-scoped serverless functions.

To attempt an all-Vercel deployment later, refactor first:

1. Move FastAPI routes under Vercel's Python function entrypoint.
2. Disable startup ingestion and daemon loops with `SIGNAL_AUTO_INGEST_ON_STARTUP=false` and `SIGNAL_PERIODIC_RSS=false`.
3. Move ingestion/refresh work to explicit admin endpoints, Vercel Cron, or an external worker.
4. Keep function bundles under Vercel's Python bundle limits by excluding tests, caches, local databases, and optional ML dependencies.
5. Verify article generation completes within Hobby function duration and payload limits.

For the current free-tier path, use Vercel for the frontend and a separate backend host for FastAPI.

## Backend Health Checks

Use:

```text
GET /health
```

Expected successful shape:

```json
{
  "ok": true,
  "database": {
    "ok": true,
    "type": "postgres",
    "error": ""
  }
}
```

If `database.ok` is false, the API process started but table creation or DB access failed.

## Migrations

There is no migration framework yet. `scripts/create_tables.py` executes `schema.sql` with `CREATE TABLE IF NOT EXISTS` statements.

For production-like deployments, add a real migration tool before making schema-changing releases.

## Provider Keys

Backend can run without paid/news provider keys:

- RSS/Bing/GDELT still provide source candidates.
- Gemini is required for generated article prose. If Gemini is unavailable, the write fails without saving an article.
- OpenAI claim extraction stays disabled unless explicitly enabled.

Recommended demo backend:

```env
DATABASE_URL=postgresql://...
PUBLIC_ARTICLE_BASE_URL=https://your-frontend.vercel.app
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
USE_LLM_CLAIMS=false
SIGNAL_API_TOKEN=...
SUPABASE_JWT_SECRET=...
```

## Production Gaps

Do not claim production readiness until these are addressed:

- CORS is env-driven and includes deployed frontend origins.
- User-specific endpoints enforce authentication.
- Article builds use per-job progress rather than global progress.
- Ingestion/background failures are logged and observable.
- Schema migrations are managed.
- Backend-configured deployments do not save local, quick consensus-only, or fallback articles.
- Rate limiting exists on generation endpoints.
