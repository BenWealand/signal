# Signal Dispatch / Signal News Intelligence

Signal Dispatch is a source-transparent news intelligence prototype. A reader enters a topic, the backend gathers public coverage from multiple sources, extracts claims, compares source overlap, and returns a readable article with source counts, reviewed links, and sourcing signals.

This repository contains:

- React/Vite frontend in `src/` and `components/`
- FastAPI backend in `backend/app/`
- PostgreSQL schema and query layer in `backend/app/db/`
- Local/demo scripts in `scripts/` and `backend/scripts/`
- Contributor and demo docs in `docs/`

## Current Readiness

This is a prototype/demo project, not a production-ready news system. It has live ingestion paths, optional LLM writing, Supabase auth hooks, and static fallbacks, but some flows are deliberately demo-friendly. Fast article mode prioritizes responsiveness and does not run the full consensus pipeline.

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
```

Common local variables:

```env
VITE_SIGNAL_API_URL=http://127.0.0.1:8000
PUBLIC_ARTICLE_BASE_URL=http://127.0.0.1:5175
```

Optional keys:

```env
GEMINI_API_KEY=
OPENAI_API_KEY=
NEWS_API_KEY=
CURRENTS_API_KEY=
GNEWS_API_KEY=
GUARDIAN_CONTENT_API_KEY=
SIGNAL_API_TOKEN=
PROMPT_BLACKLIST=
PROMPT_BLACKLIST_REGEX=
```

See `.env.example` and [backend/README.md](backend/README.md) for the full variable list.

## Frontend Only

Use this when you only want the UI with static fallback data.

```bash
npm install
npm run dev
```

Open the Vite URL shown in the terminal. Without `VITE_SIGNAL_API_URL`, backend-backed features will be offline and static/generated fallbacks will be used.

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

Supabase Auth is optional. For frontend auth forms, set:

```env
VITE_SUPABASE_URL=
VITE_SUPABASE_ANON_KEY=
```

The current backend user upsert path stores local user rows by email and does not enforce server-side Supabase auth.

## Provider Behavior

- RSS, Bing News RSS, and GDELT are the main low-cost discovery paths.
- Guardian, NewsAPI, Currents, and GNews keys add more source candidates when configured.
- Gemini writes polished article prose when `GEMINI_API_KEY` is set. If Gemini is missing, rate-limited, or failing, the backend uses rule-based prose.
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
- [Demo script](docs/demo-script.md)
- [Project rundown](docs/project-rundown.md)
- [X trend agent](docs/x-trend-agent.md)

## Troubleshooting

`DATABASE_URL is required`

Set a PostgreSQL URL in `.env`, `backend/.env`, or your shell. SQLite is not supported by the current backend.

`Refusing to install Python packages outside a virtualenv`

Create and activate `backend/.venv`, then retry.

`Could not connect to PostgreSQL`

Check the password, hostname, network access, IP allowlist, `sslmode=require`, and whether the database is awake.

Frontend says cached/offline

Confirm `VITE_SIGNAL_API_URL` points at the backend and `GET /health` works.

Article generation returns fallback content

The backend may have too few accessible sources, missing provider keys, or an LLM rate limit. The app is designed to return a clear fallback instead of crashing.
