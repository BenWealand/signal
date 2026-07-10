# Signal News Intelligence Project Rundown

Last reviewed: 2026-05-29

## Executive Summary

This project is a full-stack prototype for **Signal Dispatch**, a source-transparent news intelligence and article-writing platform. Its core product idea is: a reader submits a topic or clicks a trend, the system gathers recent public coverage from multiple sources, extracts factual claims, compares overlap between outlets, and produces a readable article with source counts, reviewed links, and visible sourcing cues.

The application has three major parts:

1. A **React/Vite frontend** in `src/` and `components/` that presents the Signal Dispatch web experience.
2. A **FastAPI backend** in `backend/app/` that owns ingestion, article storage, article generation, user history, saved stories, search, and story-cluster APIs.
3. A set of **scripts and generated assets** that support local demos, static fallback articles, database setup, and one-command local startup.

The project is not currently a Git repository in this workspace. There is a `dist/` build, `node_modules/`, a backend database artifact named `backend/signal_news.db`, many screenshot/image artifacts at the root, and a `docs/` folder with an existing `x-trend-agent.md`.

## High-Level Product Behavior

At runtime, the application tries to behave like a news desk that can produce sourced drafts on demand:

1. The frontend loads generated articles, story clusters, trending topics, and static fallback article data.
2. The home page displays a live-looking global source map using a globe visualization.
3. A user enters a prompt such as a company, policy, event, or trend.
4. The frontend posts that prompt to the backend article-writing endpoint.
5. The backend fetches relevant articles from RSS, Bing News, GDELT, Guardian, and optional paid/news APIs.
6. The backend cleans article text, extracts entities, extracts claims, clusters related claims, and detects source consensus.
7. The backend attempts to use Gemini for polished prose if configured and allowed.
8. If Gemini is unavailable, rate-limited, or not configured, the backend falls back to rule-based article synthesis.
9. The generated article is saved in the `generated_articles` table and returned to the frontend.
10. The frontend displays the article with source counts, bias rejects, fairness/accuracy scores, source links, share tools, and save actions.

The project is explicitly built around a "spend money late" philosophy. Free and cheap discovery/processing happens before any optional LLM writing or claim extraction.

## Repository Layout

```text
.
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── clustering/
│   │   ├── db/
│   │   ├── ingest/
│   │   ├── llm/
│   │   ├── models/
│   │   ├── nlp/
│   │   ├── processing/
│   │   ├── config.py
│   │   └── main.py
│   ├── scripts/
│   ├── tests/
│   ├── README.md
│   ├── requirements.txt
│   └── signal_news.db
├── components/
│   └── ui/
├── dist/
├── docs/
├── public/
├── scripts/
├── src/
│   ├── lib/
│   ├── main.jsx
│   └── styles.css
├── .env
├── .env.example
├── Design.md
├── package.json
├── serve-dist.cjs
├── server.js
└── unbiased_news_web_platform_prd.md
```

Important root-level files:

- `package.json`: frontend scripts and npm dependencies.
- `src/main.jsx`: the main React application. This is a large single-file app.
- `src/styles.css`: the main visual system and responsive styling.
- `backend/app/main.py`: FastAPI application setup, startup tasks, CORS, routers, health endpoint.
- `backend/app/db/schema.sql`: PostgreSQL schema.
- `backend/app/processing/article_writer.py`: the core article-generation pipeline.
- `backend/README.md`: backend setup and API endpoint summary.
- `scripts/run-all.cjs`: one-command orchestrator for build, backend setup, pipeline, and servers.
- `scripts/generate-article.cjs`: command-line article generator with backend integration and static fallback.
- `public/generated-articles.json`: static fallback/generated article queue for frontend use.
- `dist/`: built frontend output.

## Frontend Overview

The frontend is a React app built with Vite. The entry point is `src/main.jsx`, and the styling is mostly centralized in `src/styles.css`.

### Frontend Dependencies

From `package.json`:

- `react`
- `react-dom`
- `vite`
- `@vitejs/plugin-react`
- `@supabase/supabase-js`
- `cobe`
- `motion`
- `@playwright/test` as a dev dependency

The notable UI-specific dependency is `cobe`, used by `components/ui/globe.tsx` to render the interactive globe.

### Frontend Environment

The frontend reads:

```text
VITE_SIGNAL_API_URL
VITE_SUPABASE_URL
VITE_SUPABASE_ANON_KEY
```

`src/main.jsx` sets:

```js
const API_BASE = import.meta.env.VITE_SIGNAL_API_URL || "";
```

If `VITE_SIGNAL_API_URL` is not present, `apiGet` and `apiPost` throw `API is not configured for this build.` The app can still show offline preview drafts for local development, but backend-configured deployments do not present those previews as generated articles.

`src/lib/supabase.js` creates the Supabase client from `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`.

### Main Frontend State

The `App` component controls most of the frontend behavior. Its core state includes:

- `prompt`: current prompt text in the writer input.
- `draftPrompt`: prompt currently being built or shown.
- `phase`: `"idle"`, `"building"`, or `"complete"`.
- `activeScreen`: current navigation screen.
- `activeSection`: current topic section.
- `accountOpen`: whether the account modal is open.
- `settingsOpen`: whether settings are open.
- `toast`: transient toast text.
- `commandArticles`: generated articles from the backend and offline/static preview entries used only when no backend URL is configured.
- `backendStories`: normalized story clusters from backend.
- `trendingTopics`: trending entity/topic data from backend.
- `apiStatus`: `"online"` or `"offline"`.
- `externalDraft`: backend-generated article currently being viewed.
- `account`: stored account object persisted in local storage.
- `savedArticles`: locally stored saved article list.
- `settings`: locally stored reader preferences.
- `newsletterEmail`: locally stored newsletter email.
- `suggestionIndex` and `typedSuggestion`: animated prompt suggestion behavior.

The frontend uses a custom `useStoredState` hook to persist account, saves, settings, and newsletter email into `localStorage`.

### Session Tracking

At load time, the app creates or restores a `SESSION_ID` in `sessionStorage`:

```js
signal-session
```

That session id is sent to the backend `/history` endpoint by `trackEvent`. This allows preference inference even when the user is not signed in.

### Frontend Data Loading

On initial load, the frontend tries to fetch these resources in parallel:

- `GET /generated-articles`
- `GET /stories`
- `GET /generated-articles/{id}` if the URL has `?article=...`
- `GET /news/trending-topics?limit=10`
- `/generated-articles.json` from the static public folder

The result is merged into frontend state:

- Generated backend articles become `commandArticles`.
- Backend story clusters are normalized by `normalizeBackendStory`.
- Trending entity/topic data becomes globe/topic content.
- Static JSON is used only as offline/local preview data when backend-generated articles are unavailable.
- A linked article from `?article=...` opens directly into the reader screen.

### Frontend Screens

The primary navigation screens are:

- `Home`
- `Latest`
- `Trends`
- `Saved`

There are also topic screens:

- `World`
- `Politics`
- `Markets`
- `Technology`
- `Climate`

#### Home Screen

The home screen displays:

- A `Globe` component with trend/story markers.
- Hero copy for Signal Dispatch.
- A compact writer panel for prompt-based article generation.
- A `NewsDashboard` showing top stories for the active section.
- A newsletter preference form.

The globe markers come from a combination of:

- Backend trending topics.
- Generated articles.
- Backend story clusters.
- Offline starter stories.

Locations are inferred from topic/article text with `LOCATION_KEYWORDS`. If no real location is detected, no globe marker is shown.

#### Latest Screen

`LatestScreen` shows filed analysis articles. It supports filtering by:

- All
- World
- Politics
- Markets
- Technology
- Climate

Each article row shows:

- Source label.
- Date.
- Headline.
- Dek/summary.
- Source count.
- `Read` action.
- `Refresh` action.

The screen displays `Live` if backend calls succeeded and `Cached` if only cached/offline data is available.

#### Trends Screen

`TrendsScreen` ranks articles by source count and displays trend cards. It also fetches `/news/trending-topics?limit=12` and shows a sidebar of entity/topic mentions.

Trend cards show:

- Rank.
- Source label.
- Headline.
- Summary/body preview.
- Source count.
- Fairness score when available.
- Open button for generated articles.

#### Topic Section Screens

`TopicSectionScreen` handles World, Politics, Markets, Technology, and Climate. It fetches:

```text
GET /news/{section}?limit=18
```

It supports:

- Writing a section brief using a predefined section query.
- Refreshing section coverage using:

```text
POST /news/refresh/{section}
```

It displays:

- Section header.
- Top story banner.
- Loading/empty states.
- Section cards with title, source count, summary/dek, and date.

There is also an older `SectionScreen` implementation in `src/main.jsx`. The active code path uses `TopicSectionScreen`.

#### Saved Screen

`SavedScreen` shows articles saved locally in `localStorage`. Saving also posts to the backend `/saved-stories` endpoint when possible.

### Article Build Screen

`BuildScreen` is shown when `phase === "building"`.

It displays:

- Pipeline stage pips: fetching, enriching, processing, consensus, writing.
- A progress label.
- Source and claim counters.
- Elapsed time.
- A fast terminal-style scrolling log.

It polls:

```text
http://localhost:8000/articles/progress
```

This is hard-coded to localhost rather than using `API_BASE`. That means production or non-local deployments may show stale/local-only progress unless this is changed.

### Article Reader Screen

`ArticleScreen` displays generated articles. It includes:

- Rewrite prompt bar.
- Save button.
- Share button.
- Copy link button.
- Share on X button.
- Print button.
- Article headline, dek, and body.
- Source-aware inline highlighting via `FactText` and `SourcedFact`.
- Article stats:
  - sources
  - bias rejects
  - fairness score
  - accuracy score
- Source links list when `sourceLinks` is present.

`SourcedFact` uses `data-source` and focusability to expose provenance in the UI.

### Account and Auth

`AccountModal` integrates with Supabase auth:

- Sign up with email/password.
- Sign in with email/password.
- Sign out.
- Store account metadata locally.
- Upsert the user into backend `/users`.
- Save newsletter email after auth.

The frontend account model includes:

```js
{
  name,
  email,
  plan,
  supabase_user_id,
  id
}
```

The backend schema includes a `supabase_user_id` column, but the current `upsert_user` query function only upserts by `name`, `email`, and `plan`. The frontend sends `supabase_user_id`, but the backend route ignores it.

### Settings and Preferences

`SettingsModal` exposes reader preferences:

- Region.
- Edition.
- Reading density.
- Minimum sources.
- Email alerts.
- Label disputed claims.

If a signed-in account has a backend id, the modal fetches:

```text
GET /users/{user_id}/preferences/auto
```

That endpoint returns inferred preferences from `user_history`, such as preferred sections and topics.

### Frontend Static Fallbacks

The app includes local/static fallback data:

- `starterStories` in `src/main.jsx`.
- `buildDraft(prompt)` simulated local draft builder.
- `public/generated-articles.json`.

If live article generation fails, `handleSubmit` and related actions wait about 7.2 seconds and then show the locally built draft.

This is useful for demos, but it means the UI can appear successful even when backend generation fails.

## Backend Overview

The backend is a FastAPI application in `backend/app`. It is organized into API routes, ingestion modules, processing modules, LLM helpers, NLP helpers, database access, and tests.

### Backend Dependencies

The backend uses:

- `fastapi`
- `uvicorn`
- `python-dotenv`
- `pydantic[email]`
- `psycopg2-binary`
- `spacy`
- `openai`
- `trafilatura`
- `sentence-transformers`
- `torch`
- `transformers`
- `scipy`
- `numpy`
- `scikit-learn`
- supporting packages for extraction, dates, tokenization, and embeddings.

The `backend/requirements.txt` comments say versions are pinned to releases on or before 2026-05-05 as a supply-chain precaution.

### Backend Environment Variables

`backend/app/config.py` reads:

```text
DATABASE_URL
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
OPENAI_API_KEY
GEMINI_API_KEY
NEWS_API_KEY
CURRENTS_API_KEY
GNEWS_API_KEY
GUARDIAN_CONTENT_API_KEY
GOOGLE_FACT_CHECK_API_KEY
SIGNAL_API_TOKEN
PUBLIC_ARTICLE_BASE_URL
RSS_FEEDS
GDELT_QUERIES
CLAIM_MODEL
SUMMARY_MODEL
GEMINI_MODEL
USE_LLM_CLAIMS
```

Defaults:

- `CLAIM_MODEL`: `gpt-4o-mini`
- `SUMMARY_MODEL`: `gpt-4o-mini`
- `GEMINI_MODEL`: `gemini-flash-latest`
- `USE_LLM_CLAIMS`: `false`
- `app_name`: `Signal News Intelligence API`

Important note: the current `backend/app/db/connection.py` uses `psycopg2.connect(settings.database_url)` and the schema uses PostgreSQL features such as `SERIAL`, `TIMESTAMPTZ`, `UUID`, `ILIKE`, and `NOW() - INTERVAL`. A PostgreSQL-compatible `DATABASE_URL` is required. `backend/signal_news.db` is a legacy/demo artifact and is not read by the current backend.

### FastAPI Setup

`backend/app/main.py` creates:

```py
app = FastAPI(title=settings.app_name)
```

It enables CORS for local frontend origins:

- `http://127.0.0.1:5175`
- `http://localhost:5175`
- `http://127.0.0.1:5173`
- `http://localhost:5173`
- `http://127.0.0.1:4173`
- `http://localhost:4173`

It includes routers:

- `story_router`
- `article_router`
- `search_router`
- `user_router`
- `news_router`

### Backend Startup Behavior

On FastAPI startup:

1. `create_tables()` runs the SQL schema.
2. Database health is stored in `_database_status`.
3. Sentence-transformer embeddings are warmed up in the background.
4. A daemon thread starts `_startup_pipeline`.
5. A daemon thread starts `_periodic_rss_refresh` every 900 seconds.

`_startup_pipeline`:

1. Fetches RSS snippets across all sections with `fetch_all_rss_fast`.
2. Inserts and enriches them with `_ingest_and_enrich`.
3. Generates one article per section using `_fetch_section`.

`_periodic_rss_refresh`:

1. Sleeps for 15 minutes.
2. Fetches all RSS snippets again.
3. Enriches them.
4. Regenerates section articles.

Most exceptions in startup/daemon tasks are swallowed. This keeps the server alive, but it also makes failures easy to miss unless `/health`, logs, or downstream UI state are checked.

### Health Endpoint

```text
GET /health
```

Returns:

- `ok: true`
- database status object
- `mode: "demo"` if no OpenAI key, otherwise `"llm"`
- number of RSS feeds known to the app

## API Surface

### Story Routes

Defined in `backend/app/api/routes_stories.py`.

```text
GET /stories
GET /stories/latest
GET /stories/trending
GET /stories/{story_id}
GET /stories/{story_id}/claims
GET /stories/{story_id}/consensus
```

These routes are thin wrappers around `backend/app/db/queries.py` story and consensus functions.

### Article Routes

Defined in `backend/app/api/routes_articles.py`.

```text
GET /articles/progress
GET /articles/test-gemini
GET /articles/{article_id}
GET /articles/source/{source_name}
GET /sources
GET /generated-articles
GET /generated-articles/{article_id}
POST /articles/generate-from-trend
POST /agents/x/article-reply
POST /articles/write
```

Key behavior:

- `/articles/progress` exposes global article-writing progress.
- `/articles/test-gemini` makes a minimal Gemini writer call and returns success/error details.
- `/articles/write` is the normal reader-facing prompt-to-article endpoint.
- `/articles/generate-from-trend` is protected by `SIGNAL_API_TOKEN`.
- `/agents/x/article-reply` is protected by `SIGNAL_API_TOKEN` and returns a generated article plus X-ready reply text.

Agent auth accepts either:

```text
X-Signal-Token: ...
Authorization: Bearer ...
```

If `SIGNAL_API_TOKEN` is not configured, protected agent endpoints fail closed with HTTP 503.

### News Routes

Defined in `backend/app/api/routes_news.py`.

```text
GET /news/{section}
POST /news/refresh/{section}
GET /news/trending-topics
POST /ingest/rss
POST /ingest/rss/{section}
GET /ingest/rss/status
```

Section prompts:

```py
world: "international diplomacy conflict global affairs"
politics: "congress senate legislation government policy"
markets: "stock market economy financial inflation interest rates"
technology: "artificial intelligence semiconductor technology cybersecurity"
climate: "climate change environment renewable energy weather"
source-wire: "breaking news wire services latest"
```

`GET /news/{section}` merges:

1. Generated articles matching section keywords.
2. Story clusters matching section keywords as fallback.

`GET /news/trending-topics` attempts, in order:

1. Named entities mentioned by two or more articles in the last 72 hours.
2. Named entities in the last 72 hours regardless of the two-source threshold.
3. Story cluster topic labels with member counts.
4. Recent processed article titles.

### Search Routes

Defined in `backend/app/api/routes_search.py`.

```text
GET /search?q=...
GET /entities/{entity_name}
```

Search uses `ILIKE` against article title and clean text.

### User Routes

Defined in `backend/app/api/routes_users.py`.

```text
POST /users
GET /users/{user_id}/saved
GET /users/{user_id}/preferences/auto
POST /history
POST /saved-stories
```

These support:

- User upsert.
- Saved stories.
- History recording.
- Automatic preference inference.

## Database Model

The schema is in `backend/app/db/schema.sql`.

### `sources`

Stores known source metadata.

Columns include:

- `id`
- `source_name`
- `domain`
- `country`
- `language`
- `source_type`
- `reliability_tier`
- `political_lean_optional`
- `rss_url`
- `is_active`
- `created_at`

`source_name` is unique.

### `articles`

Stores source articles and processing status.

Columns include:

- `id`
- `source_id`
- `source_name`
- `title`
- `normalized_title`
- `url`
- `published_at`
- `description`
- `raw_text`
- `clean_text`
- `topic`
- `language`
- `status`
- `duplicate_of`
- `created_at`

`url` is unique.

`status` is commonly:

- `new`
- `processed`
- `duplicate`

### `entities`

Stores named entities extracted from articles.

Columns include:

- `article_id`
- `entity_text`
- `entity_type`
- `start_char`
- `end_char`

### `claims`

Stores factual claims extracted from article text.

Columns include:

- `article_id`
- `claim_text`
- `claim_type`
- `entities`
- `source_name`
- `claim_order`
- `confidence_score`

`entities` is stored as JSON text.

### `story_clusters`

Stores story-level clusters.

Columns include:

- `id`
- `topic_label`
- `created_at`
- `updated_at`

### `story_cluster_articles`

Join table between story clusters and articles.

Unique constraint:

```sql
UNIQUE(story_cluster_id, article_id)
```

### `consensus_claims`

Stores grouped claim-consensus results.

Columns include:

- `story_cluster_id`
- `claim_text`
- `support_count`
- `source_list`
- `status`
- `source_diversity_score`
- `confidence_score`

`source_list` is JSON text.

### `generated_summaries`

Stores generated cluster summaries.

Columns include:

- `story_cluster_id`
- `summary_text`
- `model_name`
- `version`
- `created_at`

### `generated_articles`

Stores reader-facing generated articles.

Columns include:

- `id`
- `source`
- `tag`
- `trend_url`
- `prompt`
- `headline`
- `dek`
- `summary`
- `body`
- `facts`
- `terms`
- `sources`
- `source_count`
- `denied_for_bias`
- `fairness_score`
- `accuracy_score`
- `status`
- `created_at`

`body`, `facts`, `terms`, and `sources` are JSON-encoded strings.

### `users`

Stores users.

Columns include:

- `id`
- `name`
- `email`
- `plan`
- `supabase_user_id`
- `created_at`

`email` is unique. `supabase_user_id` is unique.

### `user_preferences`

Stores explicit user preferences.

Columns include:

- `region`
- `edition`
- `density`
- `source_threshold`
- `email_alerts`
- `show_disputed_claims`

### `saved_stories`

Stores saved stories/articles.

Columns include:

- `user_id`
- `story_id`
- `title`
- `source_count`
- `saved_at`

### `user_history`

Stores behavioral events.

Columns include:

- `user_id`
- `session_id`
- `action_type`
- `topic`
- `section`
- `prompt`
- `article_id`
- `created_at`

Used by auto-preference inference.

## Database Access Layer

`backend/app/db/connection.py`:

- Opens PostgreSQL connections with `psycopg2`.
- Uses `RealDictCursor`.
- Provides `get_connection()` context manager.
- Runs schema statements in `create_tables()`.

`backend/app/db/queries.py` contains most persistence logic:

- Source upsert/listing.
- Article insert/list/get/update.
- Duplicate checks.
- Entity replacement.
- Claim replacement.
- Cluster creation.
- Consensus replacement.
- Generated summary saving.
- Story listing/detail.
- Search.
- Entity article lookup.
- Generated article save/list/get.
- User upsert.
- Saved story save/list.
- Section-specific generated story queries.
- History recording.
- Preference inference.

The query layer serializes dates to ISO strings via `row_to_dict`.

## Ingestion System

The ingestion layer lives in `backend/app/ingest`.

### Article Reader

`article_reader.py` handles:

- Google News RSS URL unwrapping.
- Bing News redirect unwrapping.
- Raw HTML fetching.
- Article text extraction with `trafilatura`.
- Fallback parsing with a custom `HTMLParser`.
- Boilerplate filtering.

Important behavior:

- Google News RSS links are decoded to real publisher URLs when possible.
- Bing `apiclick` URLs are decoded from the `url=` query parameter.
- `trafilatura` is preferred for extraction.
- A custom parser collects text from `p`, `h1`, `h2`, `h3`, and `li` tags if `trafilatura` is unavailable or fails.
- Script, style, nav, header, footer, forms, asides, and other non-article regions are skipped.

### RSS Ingestion

`rss_ingest.py` is the largest ingestion module. It defines section feeds for:

- World.
- Politics.
- Markets.
- Technology.
- Climate.
- Source wire.

It includes feeds from AP, BBC, Al Jazeera, NPR, The Guardian, PBS, Deutsche Welle, Politico, The Hill, CNBC, MarketWatch, Reuters, Ars Technica, Wired, MIT Technology Review, TechCrunch, The Verge, Inside Climate News, and Grist.

Primary functions:

- `fetch_section_rss(section, enrich=True, max_articles=40, enrich_workers=10)`
- `fetch_all_rss_fast(max_per_section=8)`
- `enrich_articles_in_background(articles, workers=8)`
- `fetch_articles_for_query(query, enrich=True, max_articles=50, enrich_workers=20)`

`fetch_articles_for_query` combines:

1. Bing News RSS.
2. Guardian API.
3. NewsAPI.
4. Currents API.
5. GNews API.
6. Topic-specific RSS feeds.
7. Base wire feeds.

It intentionally excludes Google News for query-time article generation because Google News URLs often resolve to a JavaScript shell that provides little extractable text.

Topic-specific feed detection includes:

- NFL.
- NBA.
- MLB.
- NHL.
- Soccer.
- Tech.
- Crypto.
- Science.

### GDELT Ingestion

`gdelt_ingest.py` uses GDELT Doc API v2.

It converts prompts into a GDELT query by:

- Quoting meaningful multi-word prompts.
- Appending `sourcelang:english`.
- Restricting results to a two-week timespan.
- Sorting by hybrid relevance.

It relevance-filters results using keyword overlap between prompt words and article title/snippet.

### Other Source APIs

The project includes separate modules for:

- `guardian_ingest.py`
- `newsapi_ingest.py`
- `currents_ingest.py`
- `gnews_ingest.py`

These are called by `fetch_articles_for_query` when their API keys are present. Failures generally return empty lists so the pipeline can continue.

### Source Registry

`source_registry.py` provides:

- Blocked-domain filtering.
- Domain extraction from URLs.
- Source-name guessing from URLs.

The article writer uses this to avoid non-article/social domains.

## Processing Pipeline

There are two related processing paths:

1. The general batch pipeline in `backend/app/processing/pipeline.py`.
2. The prompt-to-article pipeline in `backend/app/processing/article_writer.py`.

### Batch Pipeline

`run_pipeline()`:

1. Lists articles needing processing.
2. Skips duplicates.
3. Cleans article text.
4. Extracts entities.
5. Extracts claims.
6. Marks article as processed.
7. Replaces entity and claim rows.
8. Clusters processed articles.
9. Creates story clusters.
10. Detects consensus.
11. Saves consensus claims.
12. Generates summaries.

This produces story cluster data for `/stories` endpoints.

### Prompt Article Pipeline

`write_article_from_prompt(prompt, limit=50, use_gemini=True, mode="thorough")` is the main article-generation entry point.

It supports two modes:

- `fast`
- `thorough`

The frontend currently calls `/articles/write` with `mode: "fast"` and `limit: 10`.

#### Fast Mode

`_fast_article_from_prompt`:

1. Sets progress to `fetching`.
2. Fetches query RSS/Bing/API candidates and GDELT candidates in parallel.
3. Merges candidates by URL.
4. Supplements from cached DB articles if fewer than four candidates are found.
5. If no candidates exist, refuses the write.
6. Uses snippet/raw text without full consensus processing.
7. Requires Gemini to write the article body.
8. Saves the generated article only after Gemini returns usable prose.

Fast mode is optimized for latency while still requiring Gemini-written prose.

#### Thorough Mode

The thorough path:

1. Sets progress to `fetching`.
2. Fetches live source candidates from query feeds and GDELT in parallel.
3. Deduplicates by URL.
4. Blocks social/non-article domains.
5. Filters to mostly Latin titles.
6. Supplements from cached DB articles if live candidates are sparse.
7. Requires at least four candidates with real text over 120 characters.
8. Inserts and processes articles in parallel:
   - clean text
   - entities
   - claims
9. Creates a story cluster named after the prompt.
10. Retrieves cluster claims.
11. Runs semantic consensus detection.
12. Saves consensus claims.
13. Synthesizes an article.
14. Saves the generated article.

If any major quality gate fails, the system refuses the write instead of saving a non-Gemini fallback article.

### Build Progress

`article_writer.py` keeps global progress state:

```py
{
  "active": False,
  "prompt": "",
  "stage": "idle",
  "stage_label": "Waiting",
  "sources_found": 0,
  "sources_enriched": 0,
  "claims_extracted": 0,
  "started_at": 0.0,
  "elapsed_s": 0,
}
```

This is read by:

```text
GET /articles/progress
```

The frontend build screen polls it.

Because this is a single global state object, simultaneous article builds will overwrite each other's progress display.

## NLP and Claim Logic

### Text Cleaning

`clean_text.py` normalizes article text and removes obvious junk such as ads/subscription fragments.

### Deduplication

`dedupe.py` handles:

- Title normalization.
- Title similarity.
- Probable duplicate detection.

The database insert path uses this to mark duplicates by URL, normalized title, source, and title similarity.

### Story Clustering

`clustering/story_clusterer.py` clusters articles by topic keys. It is intentionally simple and appears aimed at MVP behavior rather than production-grade clustering.

### Entity Extraction

`nlp/ner.py` tries to load spaCy and falls back to local/simple extraction if spaCy is unavailable. Entities are stored in the `entities` table and used for trending topics and claim extraction context.

### Sentiment/Framing

`nlp/sentiment.py` provides `framing_score(text)`. It is small and heuristic-based.

### Claim Extraction

`llm/claim_extractor.py` supports two modes:

1. Local rule-based extraction by default.
2. LLM extraction when `USE_LLM_CLAIMS=true` and `OPENAI_API_KEY` is set.

The default local extractor:

- Splits text into sentences.
- Skips short sentences.
- Skips opinion/prediction markers such as `should`, `could`, `might`, `believes`, and `critics say`.
- Assigns higher confidence when sentence includes numbers or factual verbs like passed, approved, reported, said, or announced.
- Marks claims with digits as `number`; otherwise `event`.
- Matches known entities by substring.

### Consensus Detection

`llm/consensus.py` groups claims by meaning.

It tries:

1. Semantic grouping with sentence-transformer embeddings.
2. Jaccard word-overlap fallback if embeddings fail.

Status rules:

- Claims from two or more distinct sources become `supported`.
- Single-source low-confidence claims become `uncertain`.
- Other single-source claims become `unique`.

Each consensus item includes:

- `claim_text`
- `support_count`
- `sources`
- `status`
- `source_diversity_score`
- `confidence_score`
- `method`

### Embeddings

`llm/embeddings.py` loads a sentence-transformer model, exposes a warmup function, creates embeddings, and computes cosine similarity matrices. The FastAPI startup path attempts to warm this model in the background.

## LLM and Article Synthesis

### OpenAI Client

`llm/client.py` wraps OpenAI text completion behavior and checks for `OPENAI_API_KEY`. It is primarily used for optional LLM claim extraction and summaries.

### Gemini Writer

`llm/gemini_writer.py` handles polished article writing with Google Gemini.

Important details:

- API base: `https://generativelanguage.googleapis.com/v1beta/models`
- Default model from settings: `gemini-flash-latest`
- Local rate limit: 10 calls per 60 seconds.
- Cooldown after HTTP 429: 65 seconds.
- Source material budget: about 9,000 total characters.
- Per-source budget: about 1,300 characters.
- Prompt requires:
  - 6-8 substantive paragraphs.
  - AP style.
  - Only facts from supplied source material.
  - Attribution to specific outlets.
  - No headline/byline/dateline.
  - No markdown.

If Gemini fails, generated article writes fail without saving an article.

### Article Object Builder

`_article_from_consensus` builds the final article object:

- `id`
- `source`
- `tag`
- `trendUrl`
- `prompt`
- `headline`
- `dek`
- `summary`
- `body`
- `facts`
- `terms`
- `createdAt`
- `sourceCount`
- `deniedForBias`
- `fairnessScore`
- `accuracyScore`
- `scoreMetadata`
- `sources`
- `sourceLinks`
- `consensus`
- `generation_mode`
- `source_quality`
- `consensus_level`
- `used_live_sources`
- `fallback_reason` only on legacy rows that predate the Gemini-only policy

The frontend expects this mostly camelCase shape. The newer source-intelligence
metadata intentionally uses snake_case because it is passed through from the
backend pipeline and describes backend generation behavior. `fairnessScore` and
`accuracyScore` are legacy heuristic UI estimates; `scoreMetadata` explains that
they are not audited factual-accuracy or bias ratings.

## Command and Utility Scripts

### Frontend npm Scripts

From `package.json`:

```text
npm run dev
npm run article:trend
npm run build
npm run start:all
npm run serve
npm run preview
```

Behavior:

- `dev`: starts Vite on `127.0.0.1`.
- `article:trend`: runs `scripts/generate-article.cjs`.
- `build`: runs Vite build.
- `start:all`: runs `scripts/run-all.cjs`.
- `serve`: serves `dist/` through `serve-dist.cjs`.
- `preview`: Vite preview on `127.0.0.1`.

### `scripts/run-all.cjs`

This is the most complete local orchestration script. It:

1. Finds Python.
2. Installs frontend dependencies if `node_modules` is absent.
3. Builds the frontend with `VITE_SIGNAL_API_URL` defaulting to `http://127.0.0.1:8000`.
4. Installs backend dependencies.
5. Creates backend tables.
6. Seeds source registry.
7. Loads sample articles.
8. Optionally fetches configured RSS feeds.
9. Optionally fetches configured GDELT candidates.
10. Runs the backend article pipeline.
11. Starts the backend API on `127.0.0.1:8000`.
12. Starts the static frontend server on `127.0.0.1:5175`.

Potential friction: it runs `python -m pip install -r requirements.txt` against whichever Python is found, not necessarily an isolated virtual environment.

### `scripts/generate-article.cjs`

This script creates a generated article from a command-line prompt.

It first tries to post to:

```text
POST /articles/generate-from-trend
```

using `SIGNAL_API_URL` and optional `SIGNAL_API_TOKEN`.

If the backend is unavailable or rejects the request, it builds a simulated local article and writes it to:

- `public/generated-articles.json`
- `dist/generated-articles.json` if `dist/` exists

Usage:

```text
npm run article:trend -- "trend prompt" --source openclaw-x --url https://x.com/...
```

### Static Servers

`server.js` serves files from the project root and defaults to port `5173`.

`serve-dist.cjs` serves the built `dist/` folder and defaults to port `4173`, but `scripts/run-all.cjs` starts it with `PORT=5175`.

`serve-dist.cjs` has SPA fallback behavior: unknown paths serve `dist/index.html`.

## Backend Scripts

Important backend scripts in `backend/scripts/`:

- `create_tables.py`: creates database tables from schema.
- `seed_sources.py`: seeds source registry.
- `load_sample_articles.py`: loads sample article data.
- `discover_articles.py`: runs discovery helpers.
- `fetch_rss.py`: fetches configured RSS feeds.
- `fetch_gdelt.py`: fetches configured GDELT candidates.
- `run_pipeline.py`: runs the processing pipeline.
- `diagnose_fetch.py`: fetch diagnostics.
- `diagnose_pipeline.py`: pipeline diagnostics.
- `rss_stats.py`: RSS status/statistics.
- `migrate_add_rss_url.py`: migration helper.
- `test_bing.py`, `test_guardian.py`, `test_guardian2.py`, `test_guardian_debug.py`, `test_embeddings.py`: manual/debug scripts.

## Testing

The test suite is in `backend/tests/` and uses Python `unittest`.

Existing tests cover:

- Agent token behavior and X prompt construction.
- Article text parser behavior.
- Rule-based claim extraction.
- Text cleaning.
- Consensus support requiring multiple sources.

Files:

- `test_agent_access.py`
- `test_article_reader.py`
- `test_claims.py`
- `test_clean_text.py`
- `test_consensus.py`

There are no obvious frontend tests in the repository. `@playwright/test` is installed, but no Playwright test files were found in the top-level source scan.

## Static and Generated Assets

The root contains many screenshot-like PNG files, including:

- `signal-home.png`
- `signal-home-mobile.png`
- `signal-command-desk.png`
- `signal-live-api.png`
- `signal-reader-site.png`
- `signal-prompt-sourced.png`
- others showing article, writing, mobile, hover, and functionality states.

These appear to be design/verification artifacts rather than runtime assets imported by the app.

`public/generated-articles.json` is used as a static generated article queue. The frontend loads it as a fallback. The command article script writes to it.

## X Agent Integration

There is existing documentation in `docs/x-trend-agent.md`, and the backend exposes a dedicated endpoint:

```text
POST /agents/x/article-reply
```

Expected payload:

```json
{
  "prompt": "",
  "snippet": "",
  "trending_topic": "#Example",
  "trend_url": "https://x.com/...",
  "source": "x-agent",
  "tag": "x-trend",
  "limit": 12,
  "mode": "fast"
}
```

The route:

1. Validates `SIGNAL_API_TOKEN`.
2. Builds a prompt from `prompt`, `trending_topic`, and/or `snippet`.
3. Generates an article.
4. Saves it.
5. Builds a public article URL using `PUBLIC_ARTICLE_BASE_URL`.
6. Returns a short X-ready reply text.

This is meant for an external X/trend agent that notices a topic and asks Signal to produce a sourced article link.

## Main End-to-End Flows

### Local Startup Flow

Typical full startup through `npm run start:all`:

1. Build frontend.
2. Install backend Python dependencies.
3. Create database tables.
4. Seed source records.
5. Load sample articles.
6. Optionally fetch RSS/GDELT based on env.
7. Run processing pipeline.
8. Start FastAPI backend.
9. Start static frontend server.

Expected URLs:

```text
Frontend: http://127.0.0.1:5175/
Backend:  http://127.0.0.1:8000/
Docs:     http://127.0.0.1:8000/docs
```

### User Prompt Flow

1. User submits prompt on home or section page.
2. Frontend sets `phase` to `building`.
3. Frontend posts:

```json
{
  "prompt": "topic text",
  "source": "reader-prompt",
  "tag": "prompt",
  "limit": 10,
  "mode": "fast"
}
```

to:

```text
POST /articles/write
```

4. Frontend shows build screen and polls progress.
5. Backend fast pipeline fetches candidates.
6. Backend synthesizes article.
7. Backend saves generated article.
8. Frontend normalizes it and shows reader screen.
9. User can save, share, copy link, share to X, or print.

### Section Refresh Flow

1. User opens a section page.
2. Frontend fetches:

```text
GET /news/{section}?limit=18
```

3. User clicks refresh.
4. Frontend posts:

```text
POST /news/refresh/{section}
```

5. Backend queues background article generation for that section prompt.
6. Frontend waits about eight seconds and reloads stories.

### Backend Startup Ingest Flow

1. FastAPI starts.
2. Tables are created.
3. RSS snippets are fetched quickly across sections.
4. Articles are inserted.
5. Enrichment tries to fetch full article text.
6. Text is cleaned.
7. Entities and claims are extracted.
8. Section articles are generated without Gemini to preserve quota.
9. A periodic refresh repeats every 15 minutes.

## Important Mismatches and Risks

### Legacy SQLite Artifact

The current implementation uses `psycopg2` and PostgreSQL SQL. The old `backend/signal_news.db` file remains in the tree as a legacy/demo artifact, but there is no active SQLite adapter.

### Build Progress Uses Hard-Coded Backend URL

`BuildScreen` polls:

```text
http://localhost:8000/articles/progress
```

It does not use `API_BASE`. This can break deployed builds or alternate local ports.

Recommended fix: use `${API_BASE}/articles/progress` with a localhost fallback.

### Fast Mode Does Not Actually Perform Full Consensus

The frontend uses `mode: "fast"`, and fast mode calls `_article_from_consensus` with an empty consensus list. That gives a quick article-like result but does not run the full claim consensus path.

Recommended fix: decide whether reader-facing article generation should default to `thorough`, expose both modes clearly, or label fast drafts as provisional in the UI.

### Single Global Progress State

Article progress is a single global dictionary. Concurrent builds will overwrite one another.

Recommended fix: return a build id and track progress per build/job.

### Many Backend Exceptions Are Silently Swallowed

Startup, refresh, ingest, and background tasks often use broad `except Exception: pass`. This keeps demos resilient but makes production debugging hard.

Recommended fix: add structured logging and error counters.

### Supabase User ID Is Not Persisted

The frontend sends `supabase_user_id`, but `routes_users.py` and `queries.upsert_user` do not persist it.

Recommended fix: update `UserPayload` and `upsert_user` to store `supabase_user_id`.

### Gemini 429 Fallback Is Unreachable

`gemini_writer.py` has fallback-model logic after an immediate `return None` in the 429 branch. That code cannot execute.

Recommended fix: remove the early return or remove the dead fallback block.

### Frontend Has Large Single-File Component Structure

`src/main.jsx` is over 70 KB and contains helpers, API calls, app state, screens, modals, article reader logic, auth, and utility functions.

Recommended fix: split into:

- `api/client.js`
- `hooks/useStoredState.js`
- `components/Header.jsx`
- `components/ArticleScreen.jsx`
- `components/BuildScreen.jsx`
- `screens/Home.jsx`
- `screens/Latest.jsx`
- `screens/Trends.jsx`
- `screens/Section.jsx`
- `screens/Saved.jsx`
- `components/modals/AccountModal.jsx`
- `components/modals/SettingsModal.jsx`

### Offline Preview Must Not Hide Backend Failures

If `VITE_SIGNAL_API_URL` is configured, `/articles/write` failures are shown as clear errors and no local article is generated. Offline preview drafts are only available when the frontend has no configured backend API URL.

### Requirements Are Heavy

The backend installs PyTorch, transformers, sentence-transformers, spaCy, and extraction libraries. This is expensive for local setup and deployment.

Recommended fix: split dependencies into core and ML extras, or lazy-load ML components in a worker image.

### Generated Article Scoring Is Heuristic

Fairness, accuracy, and denied-for-bias scores are generated by simple formulas. They are useful as UI signals but should not be treated as audited metrics.

Recommended fix: rename or explain them as heuristic confidence indicators unless a formal scoring methodology is implemented.

## Security Notes

Positive security choices:

- Agent endpoints fail closed if `SIGNAL_API_TOKEN` is not configured.
- Token comparison uses `secrets.compare_digest`.
- Static servers block path traversal by checking resolved paths.
- Backend CORS is limited to local frontend origins.
- API keys are loaded from environment variables.

Areas to harden:

- Keep `SUPABASE_JWT_SECRET` configured so user-specific routes can validate Supabase JWTs.
- Do not accept client-supplied `user_id` without route-guard verification.
- Add rate limiting to article-generation endpoints.
- Add request size limits for prompts/snippets.
- Store fewer sensitive values in local storage if user accounts become real.
- Avoid broad exception swallowing around ingestion and agent routes.

## Operational Notes

### Running Frontend Only

```bash
npm install
npm run dev
```

For live backend calls, set:

```text
VITE_SIGNAL_API_URL=http://127.0.0.1:8000
```

### Running Backend Only

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python scripts/create_tables.py
uvicorn app.main:app --reload --port 8000
```

A valid PostgreSQL `DATABASE_URL` is required by the current code.

### Running Both

```bash
npm run start:all
```

This is the intended all-in-one local startup command, but it installs Python dependencies into the discovered Python environment unless that environment is already activated.

## Existing Tests and Suggested Next Tests

Existing tests are good coverage for small units, but they do not cover the full API or frontend.

Suggested backend tests:

- `POST /articles/write` fast fallback behavior with mocked ingestion.
- `POST /articles/write` thorough behavior with mocked sources and DB.
- `GET /news/{section}` generated-article and story-cluster merge behavior.
- `GET /news/trending-topics` fallback ladder.
- `save_generated_article` serialization/deserialization.
- Supabase user id persistence once fixed.
- Gemini writer rate-limit behavior.

Suggested frontend tests:

- Home prompt submits and transitions to build screen.
- Successful article response transitions to article reader.
- API failure visibly labels local fallback.
- `?article=...` deep link opens article.
- Section refresh triggers backend and reloads.
- Account modal sign-in/up error handling.
- Source hover/focus behavior in article reader.

## Architectural Strengths

- Clear product concept: source overlap and claim consensus as the basis for generated reporting.
- Backend has modular boundaries for ingestion, processing, NLP, LLM helpers, DB, and routes.
- The article pipeline fails closed for generated articles when Gemini or source coverage is unavailable.
- The system can run in a cheap/free-source mode before optional LLM work.
- Agent integration is already protected by a token and returns the exact artifact an X bot would need.
- The frontend has useful local/offline preview resilience when no backend API URL is configured.
- The database model is broad enough to support stories, articles, claims, consensus, generated articles, users, preferences, saves, and history.

## Architectural Weaknesses

- Frontend complexity is concentrated in one large file.
- A legacy SQLite artifact remains in the tree even though the documented backend path is now PostgreSQL.
- Live article-writing defaults to fast mode, which bypasses full consensus.
- Errors are too often swallowed silently.
- No job queue exists for expensive article builds.
- Progress tracking is global, not per request.
- User-specific APIs are not fully authenticated.
- Generated scoring is heuristic but displayed with strong labels.
- Frontend and backend shape conversions rely on ad hoc camelCase/snake_case normalization.
- No frontend test suite is present.

## Recommended Roadmap

### First Priority

1. Fix the README/database mismatch.
2. Make build progress use `API_BASE`.
3. Add clear UI labeling for fast/local fallback drafts.
4. Log backend ingestion and article-generation failures.
5. Store `supabase_user_id` in the backend user upsert path.

### Second Priority

1. Split `src/main.jsx` into focused modules.
2. Add API integration tests with mocked ingestion.
3. Add Playwright smoke tests for the main frontend flows.
4. Add per-build progress/job ids.
5. Make article generation mode explicit in the UI.

### Third Priority

1. Move expensive article builds to a job queue.
2. Separate backend dependency groups into core and ML extras.
3. Implement authenticated user APIs.
4. Formalize fairness/accuracy scoring or rename them as heuristic signals.
5. Add observability around source health, enrichment success, LLM usage, and generation failures.

## Mental Model for New Contributors

The easiest way to understand the project is to follow a generated article from prompt to page:

1. The user submits a prompt in `src/main.jsx`.
2. `apiPost("/articles/write", ...)` sends the prompt to FastAPI.
3. `routes_articles.write_article` calls `write_article_from_prompt`.
4. `article_writer.py` fetches candidate articles from live feeds and GDELT.
5. It filters, deduplicates, and enriches candidate source articles.
6. In thorough mode, it inserts articles, extracts clean text, entities, and claims.
7. It groups claims with semantic/Jaccard consensus.
8. It asks Gemini to write from source material if configured.
9. If Gemini is unavailable, it writes a rule-based article.
10. `queries.save_generated_article` stores the article.
11. The frontend receives the article, normalizes it, and renders `ArticleScreen`.
12. The user can save/share/deep-link the generated article.

That flow is the heart of the project. Most files either feed it with source material, display its result, persist its artifacts, or support automated/agent-triggered versions of the same action.
