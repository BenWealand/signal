# Demo Script

Use this when showing Signal Dispatch to a user, investor, teammate, or reviewer.

## Pre-Demo Checklist

1. Confirm backend health:

```text
http://127.0.0.1:8000/health
```

2. Confirm frontend loads:

```text
http://127.0.0.1:5175/
```

3. Confirm `DATABASE_URL` points at PostgreSQL/Supabase Postgres.
4. Optional: confirm OpenCode Zen:

```text
http://127.0.0.1:8000/articles/test-zen
```

5. Keep a fallback prompt ready:

```text
artificial intelligence semiconductor technology cybersecurity
```

## What To Click

1. Open the home page.
2. Point out the globe and live-looking source markers.
3. Click a marker or use the prompt box.
4. Enter a specific topic:

```text
semiconductor export controls and AI chip supply chains
```

5. Click `Write`.
6. On the build screen, call out the stages:
   - fetching
   - enriching
   - processing
   - consensus
   - writing
7. When the article opens, scroll through:
   - headline and dek
   - sourced body
   - source count
   - bias rejects
   - fairness/accuracy heuristics
   - reviewed source links
8. Click `Latest`.
9. Open a generated article.
10. Click `Trends`.
11. Show ranked trend cards and trending topics.
12. Click a topic section such as `Technology`.
13. Use `Write section brief`.
14. Show `Save`, `Share`, `Copy link`, and `Share on X`.

## What To Say

Short version:

> Signal turns scattered public coverage into a readable sourced draft. It gathers coverage, removes repeats, extracts factual claims, checks which claims appear across sources, and writes an article without hiding the source trail.

Pipeline version:

> The backend starts cheap: RSS, Bing News RSS, GDELT, and optional news APIs. It cleans text, extracts entities and claims, groups similar claims, and then requires OpenCode Zen for generated article prose. If Zen or source coverage fails, the write is refused instead of saving a local or consensus-only article.

Product positioning:

> This is not trying to replace editors. It is a source-overlap workbench: faster first drafts, clearer provenance, and a visible distinction between corroborated and single-source details.

## Live Features

- React/Vite frontend.
- FastAPI backend.
- PostgreSQL/Supabase Postgres persistence.
- RSS/Bing/GDELT article discovery.
- Optional Guardian/NewsAPI/Currents/GNews enrichment.
- Article text extraction with trafilatura.
- Entity and claim extraction.
- Consensus detection with semantic similarity when ML deps are installed.
- Zen-required generated article writing.
- Clear refusal when Zen or source coverage is unavailable.
- Generated article storage and deep links.
- X agent endpoint protected by `SIGNAL_API_TOKEN`.
- Saved articles and history endpoints.

## Demo/Fallback Features

- `public/generated-articles.json` can populate the UI when backend-generated content is unavailable.
- The frontend can show a local offline preview only when no backend API URL is configured.
- Fast article mode prioritizes responsiveness and may not run the full claim-consensus path.
- Fairness and accuracy scores are heuristic display signals, not audited editorial metrics.
- Supabase Auth is wired on the frontend; set `SUPABASE_JWT_SECRET` on the backend to enforce user-route JWT checks.

Be explicit about these if the audience asks about production readiness.

## Recovery If Backend Fails

If the UI shows cached/offline:

1. Check backend:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

2. Check `DATABASE_URL`.
3. Open `/health`.
4. Confirm frontend was built or run with:

```env
VITE_SIGNAL_API_URL=http://127.0.0.1:8000
```

If article generation fails:

1. Try a broader prompt.
2. Try a topic with strong public coverage.
3. Check provider/API rate limits.
4. Use `Latest` to show existing generated/static articles.
5. Explain that backend-configured builds do not save fallback articles.

If Zen fails:

1. Show the Zen/source-coverage error.
2. Mention that the backend refuses to save non-Zen generated articles.
3. Check `/articles/test-zen` after the demo.

If PostgreSQL fails:

1. Verify Supabase project is active.
2. Check pooled connection string.
3. Add `sslmode=require` if needed.
4. Re-run:

```bash
cd backend
python scripts/create_tables.py
```

## Strongest Talking Points

- Source-overlap first, prose second.
- Cheap/free discovery before paid LLM calls.
- Graceful fallback when APIs fail.
- Built-in source links and provenance display.
- Agent-ready endpoint for X/trend workflows.
- Clear path from prototype to deployable product: Vercel frontend, Python backend, Supabase Postgres.

## Prompts That Usually Demo Well

```text
artificial intelligence semiconductor technology cybersecurity
climate change environment renewable energy weather
stock market economy financial inflation interest rates
congress senate legislation government policy
international diplomacy conflict global affairs
```

Specific prompts can be stronger, but they require enough current public coverage.
