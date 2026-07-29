# Signal Dispatch / Signal News Intelligence

Signal Dispatch is a source-transparent news intelligence prototype. A reader enters a topic, the backend gathers public coverage from multiple sources, extracts claims, compares source overlap, and returns a readable article with source counts, reviewed links, and sourcing signals.

This repository contains:

- React/Vite frontend in `src/` and `components/`
- FastAPI backend in `backend/app/`
- PostgreSQL schema and query layer in `backend/app/db/`
- Local/demo scripts in `scripts/` and `backend/scripts/`
- Contributor and demo docs in `docs/`

## Current Readiness

This is a deployment-stage prototype. Backend-generated articles require OpenCode Zen-written prose; when Zen or source coverage is unavailable, the write fails instead of saving a local, consensus-only, or fallback article. Offline preview drafts are only used when the frontend is intentionally built without a backend URL.

## Requirements

- Node.js 20+ recommended
- npm
- Python 3.11+ recommended
- PostgreSQL database, including Supabase Postgres

The backend currently uses `psycopg2` and PostgreSQL SQL. It does not use SQLite. `backend/signal_news.db` is a legacy/demo artifact and is not read by the current backend.

## Environment

Copy `.env.example` to `.env` for local frontend/full-stack runs, or copy backend-only variables into `backend/.env`.

Required backend variable:

```env
DATABASE_URL=postgresql://...
OPENCODE_API_KEY=...
GEMINI_API_KEY=...
# OpenCode Zen is primary; Gemini is called only when Zen is unavailable.
```

Common local variables:

```env
VITE_SIGNAL_API_URL=http://127.0.0.1:8000
PUBLIC_ARTICLE_BASE_URL=http://127.0.0.1:5175
CORS_ORIGINS=http://127.0.0.1:5175
```

Optional keys:

```env
OPENAI_API_KEY=
NEWS_API_KEY=
CURRENTS_API_KEY=
GNEWS_API_KEY=
GUARDIAN_CONTENT_API_KEY=
SIGNAL_API_TOKEN=
SUPABASE_JWT_SECRET=
PROMPT_BLACKLIST=
PROMPT_BLACKLIST_REGEX=
```

Deployment env checklist:

- Vercel frontend: `VITE_SIGNAL_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
- Render backend: `DATABASE_URL`, `OPENCODE_API_KEY`, `CORS_ORIGINS`, `PUBLIC_ARTICLE_BASE_URL`, `SIGNAL_API_TOKEN`, `SUPABASE_JWT_SECRET`
- GitHub Actions: `SIGNAL_API_URL`

For the Render free tier, keep memory-heavy work disabled unless you upgrade:

```env
SIGNAL_AUTO_INGEST_ON_STARTUP=false
SIGNAL_PERIODIC_RSS=false
SIGNAL_EMBEDDING_WARMUP_ON_STARTUP=false
SIGNAL_SECTION_FAST_COUNT=3
```

See `.env.example` and [backend/README.md](backend/README.md) for the full variable list.

## Frontend Only

Use this when you only want the UI with static fallback data.

```bash
npm install
npm run dev
```

Open the Vite URL shown in the terminal. Without `VITE_SIGNAL_API_URL`, backend-backed features are offline and the UI can show local preview drafts for development only.

To point the frontend at a running backend:

```bash
$env:VITE_SIGNAL_API_URL="http://127.0.0.1:8000"
npm run dev
```

For macOS/Linux:

```bash
VITE_SIGNAL_API_URL=http://127.0.0.1:8000 npm run dev
```

## Backend Only

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-core.txt
python scripts/create_tables.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

For macOS/Linux activation:

```bash
source .venv/bin/activate
```

Install optional ML dependencies only when you need semantic claim similarity and spaCy NER:

```bash
pip install -r requirements-ml.txt
```

All-in local/demo install:

```bash
pip install -r requirements.txt
```

## Full-Stack Local Run

Create a virtualenv first so the script does not install Python packages globally:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
cd ..
npm run start:all
```

`npm run start:all` will:

1. Read `.env` and `backend/.env`.
2. Require a PostgreSQL `DATABASE_URL`.
3. Install frontend deps if needed.
4. Install backend core deps into the active virtualenv.
5. Check PostgreSQL connectivity.
6. Build the frontend.
7. Create tables, seed sources, load samples, and run the pipeline.
8. Start backend on `http://127.0.0.1:8000`.
9. Start frontend on `http://127.0.0.1:5175`.

If you intentionally want a global Python install:

```bash
$env:SIGNAL_ALLOW_GLOBAL_PIP="1"
npm run start:all
```

Prefer a virtualenv instead.

## Supabase Postgres

1. Create a Supabase project.
2. Open Project Settings -> Database.
3. Copy a pooled or direct PostgreSQL connection string.
4. Set it as `DATABASE_URL`.
5. Include `sslmode=require` if your connection string/provider requires it.
6. Run `python scripts/create_tables.py` from `backend/`.

Supabase Auth is the identity provider for accounts (email/password). See [Authentication & accounts](docs/auth.md).

```env
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
VITE_SIGNAL_ADMIN_EMAILS=benwealand@gmail.com
```

Set `SUPABASE_JWT_SECRET` on the backend to verify sessions and protect user/admin routes.
Run migration `0003_user_roles_auth.sql` for `role` / `email_confirmed` / `last_login_at`.

## Provider Behavior

- RSS, Bing News RSS, and GDELT are the main low-cost discovery paths.
- Guardian, NewsAPI, Currents, and GNews keys add more source candidates when configured.
- OpenCode Zen writes article prose. If Zen is missing, rate-limited, failing, or given too few usable sources, the backend returns a clear error and does not save an article.
- OpenAI is used only for optional LLM claim extraction when `USE_LLM_CLAIMS=true` and `OPENAI_API_KEY` is set.
- Sentence-transformers/spaCy are optional ML improvements. Without them, fallback heuristics are used where the code supports it.

## Useful Commands

```bash
npm run dev
npm run build
npm run serve
npm run start:all
npm run article:trend -- "semiconductor export controls" --source openclaw-x
```

```bash
cd backend
python scripts/create_tables.py
python scripts/seed_sources.py
python scripts/load_sample_articles.py
python scripts/run_pipeline.py
python -m unittest discover tests
uvicorn app.main:app --reload --port 8000
```

## Documentation

- [Backend setup](backend/README.md)
- [Architecture](docs/architecture.md)
- [Deployment](docs/deployment.md)
- [Predeploy smoke checklist](docs/predeploy-smoke-checklist.md)
- [Demo script](docs/demo-script.md)
- [Project rundown](docs/project-rundown.md)
- [X trend agent](docs/x-trend-agent.md)
- [X usage / automation runbook](docs/x-usage.md)
- [Authentication & accounts](docs/auth.md)

## Troubleshooting

`DATABASE_URL is required`

Set a PostgreSQL URL in `.env`, `backend/.env`, or your shell. SQLite is not supported by the current backend.

`Refusing to install Python packages outside a virtualenv`

Create and activate `backend/.venv`, then retry.

`Could not connect to PostgreSQL`

Check the password, hostname, network access, IP allowlist, `sslmode=require`, and whether the database is awake.

Frontend says cached/offline

Confirm `VITE_SIGNAL_API_URL` points at the backend and `GET /health` works.

Article generation fails with a Zen/source-coverage message

The backend may have too few accessible sources, a missing `OPENCODE_API_KEY`, or a Zen rate limit. Try a more specific prompt and check Render logs for the generation failure reason.
