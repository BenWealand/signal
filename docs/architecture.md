# Contributor Architecture Guide

This guide explains the current system as it exists in code. It does not describe a production architecture that has not been built yet.

## System Map

```text
React/Vite frontend
  -> FastAPI backend
    -> PostgreSQL/Supabase Postgres
    -> RSS/Bing/GDELT/news providers
    -> trafilatura article extraction
    -> local NLP/claim logic
    -> optional ML semantic similarity
    -> optional Gemini/OpenAI
```

Main code paths:

- Frontend entry: `src/main.jsx`
- Frontend styles: `src/styles.css`
- Globe UI: `components/ui/globe.tsx`
- Backend app: `backend/app/main.py`
- API routes: `backend/app/api/`
- Article writer: `backend/app/processing/article_writer.py`
- Ingestion: `backend/app/ingest/`
- DB schema: `backend/app/db/schema.sql`
- DB queries: `backend/app/db/queries.py`

## Prompt-To-Article Flow

1. The user submits a prompt in the frontend.
2. `App.handleSubmit` posts to:

```text
POST /articles/write
```

3. The payload usually includes:

```json
{
  "prompt": "topic",
  "source": "reader-prompt",
  "tag": "prompt",
  "limit": 10,
  "mode": "fast"
}
```

4. `routes_articles.write_article` calls `write_article_from_prompt`.
5. In fast mode, the backend fetches current snippets/candidates from RSS/Bing and GDELT, supplements from cached DB results, and writes quickly.
6. In thorough mode, the backend performs more enrichment and claim-consensus processing before writing.
7. The article is saved through `queries.save_generated_article`.
8. The frontend normalizes the article and renders `ArticleScreen`.

## Article Generation Modes

### Fast Mode

Used by the frontend today.

Strengths:

- Lower latency.
- Better demo responsiveness.
- Can work from snippets and cached candidates.

Limitations:

- Does not guarantee full source enrichment.
- Does not run the full consensus path in the same way as thorough mode.
- Should be treated as a fast draft.

### Thorough Mode

Used when explicitly requested through API/scripts.

Behavior:

- Fetches more live candidates.
- Requires enough accessible source text.
- Inserts/processes articles.
- Extracts claims.
- Creates a story cluster.
- Runs consensus detection.
- Saves consensus and generated article data.

Limitations:

- Slower.
- More likely to be affected by provider timeouts, blocked article pages, ML load time, and database state.

## Source Ingestion Flow

Main modules:

- `article_reader.py`: fetches and extracts readable article text.
- `rss_ingest.py`: section RSS, query feeds, Bing News RSS, optional APIs.
- `gdelt_ingest.py`: GDELT Doc API search.
- `guardian_ingest.py`: Guardian API.
- `newsapi_ingest.py`: NewsAPI.
- `currents_ingest.py`: Currents.
- `gnews_ingest.py`: GNews.
- `source_registry.py`: blocked domains, domain parsing, source guessing.

For arbitrary prompts, `fetch_articles_for_query` combines:

1. Bing News RSS.
2. Guardian API.
3. NewsAPI.
4. Currents.
5. GNews.
6. Topic-specific RSS feeds.
7. Base wire/public feeds.

Google News is intentionally not used as the main query-time source because its links often resolve to a JavaScript shell that does not extract well.

## Startup Ingestion

`backend/app/main.py` does work on startup:

1. Creates tables.
2. Warms embeddings if available.
3. Starts `_startup_pipeline` in a daemon thread.
4. Starts `_periodic_rss_refresh` in a daemon thread.

Startup ingestion fetches RSS snippets, inserts/enriches them, and generates section articles. Many failures are swallowed to keep the server alive; contributors should add logging before relying on this operationally.

## Processing Flow

The core processing functions are:

- `clean_article_text`
- `extract_entities`
- `extract_claims`
- `detect_consensus`
- `generate_summary`
- `write_article_with_gemini`

Default behavior is local and cheap:

- Text cleanup is local.
- Entity extraction has a fallback.
- Claim extraction is rule-based unless LLM claims are enabled.
- Consensus tries semantic embeddings and falls back to Jaccard.
- Article prose uses Gemini only when configured, then falls back to rule-based paragraphs.

## Database Tables

Important tables:

- `sources`: source registry.
- `articles`: ingested article records.
- `entities`: named entities per article.
- `claims`: extracted factual claims per article.
- `story_clusters`: story/topic clusters.
- `story_cluster_articles`: cluster/article join table.
- `consensus_claims`: grouped claim support status.
- `generated_summaries`: story summaries.
- `generated_articles`: reader-facing generated articles.
- `users`: local user rows.
- `user_preferences`: explicit settings.
- `saved_stories`: saves.
- `user_history`: prompts/views/sections for preference inference.

See `backend/app/db/schema.sql` for exact columns.

## Frontend Screens

`src/main.jsx` contains the current screens:

- `Home`: globe, writer panel, top stories.
- `Latest`: generated articles and story clusters.
- `Trends`: ranked generated articles and trending entities.
- `TopicSectionScreen`: World/Politics/Markets/Technology/Climate pages.
- `Saved`: locally saved articles.
- `BuildScreen`: animated build/progress view.
- `ArticleScreen`: generated article reader.
- `AccountModal`: Supabase Auth UI and local account state.
- `SettingsModal`: local preferences and inferred backend preferences.

The file is intentionally broad right now. A contributor-friendly refactor would split it into screens, components, hooks, and API modules.

## Static Fallbacks

Static/demo data paths:

- `starterStories` in `src/main.jsx`
- `buildDraft(prompt)` in `src/main.jsx`
- `public/generated-articles.json`
- `scripts/generate-article.cjs`

These keep the demo usable when the backend or providers fail. They should not be confused with fully sourced backend-generated articles.

## Known Limitations

- Backend requires PostgreSQL, while older artifacts still reference SQLite.
- CORS origins are hard-coded for local hosts.
- Build progress is a single global object.
- Fast mode is not full consensus mode.
- User-specific backend routes do not enforce auth.
- Many background failures are swallowed.
- No schema migration framework exists.
- No frontend test suite exists.
- The frontend is concentrated in one large file.
- Heuristic scores are displayed as fairness/accuracy scores.

## Roadmap

Near-term:

1. Make CORS env-driven.
2. Label fast/local fallback drafts clearly.
3. Add backend logging for ingestion and generation.
4. Store Supabase user ids in the backend upsert path.
5. Add integration tests around `/articles/write` with mocked providers.

Medium-term:

1. Split `src/main.jsx`.
2. Add per-job article generation progress.
3. Add a migration framework.
4. Add frontend Playwright smoke tests.
5. Add authenticated user APIs.

Longer-term:

1. Move article builds to a queue/worker.
2. Add observability for source/provider health.
3. Formalize source scoring and claim confidence.
4. Add deployment configs after choosing backend host.
