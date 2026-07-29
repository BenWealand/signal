# Predeploy Smoke Checklist

Run this after Vercel and Render redeploy the latest `main`.

## Environment

Vercel frontend:

- `VITE_SIGNAL_API_URL=https://your-render-service.onrender.com`
- `VITE_SUPABASE_URL=https://your-project-ref.supabase.co`
- `VITE_SUPABASE_ANON_KEY=your-public-anon-key`

Render backend:

- `DATABASE_URL=postgresql://...`
- `OPENCODE_API_KEY=...`
- `GEMINI_API_KEY=...` (secondary fallback)
- `CORS_ORIGINS=https://your-vercel-site.vercel.app`
- `PUBLIC_ARTICLE_BASE_URL=https://your-vercel-site.vercel.app`
- `SIGNAL_API_TOKEN=...`
- `SUPABASE_JWT_SECRET=...`
- `USE_LLM_CLAIMS=false`
- `SIGNAL_AUTO_INGEST_ON_STARTUP=false`
- `SIGNAL_PERIODIC_RSS=false`
- `SIGNAL_EMBEDDING_WARMUP_ON_STARTUP=false`
- `SIGNAL_SECTION_FAST_COUNT=3`

GitHub Actions:

- `SIGNAL_API_URL=https://your-render-service.onrender.com`

## Backend

```bash
curl -fsS https://your-render-service.onrender.com/awake
curl -fsS https://your-render-service.onrender.com/health
```

Expected:

- `/awake` returns `{"ok":true,...}` quickly once the service is up.
- `/health` returns `"ok": true` and `"database": {"ok": true, ...}`.

## Cleanup

Purge obvious legacy/non-Zen generated rows before launch:

```bash
curl -X POST \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  "https://your-render-service.onrender.com/generated-articles/purge-legacy?limit=5000"
```

Expected:

- Response includes `scanned`, `deleted`, and `articleIds`.
- A second run should usually return `deleted: 0`.

## Frontend

Open the Vercel URL and verify:

- Home loads without a blank white screen.
- The prompt box says the newsroom is waking/sourcing when generating.
- A failed Zen/source write shows: `Could not generate from enough reliable sources. Try a more specific prompt.`
- No backend-configured article screen shows `local`, `demo`, `fallback`, or `preview draft` as if it were a generated article.
- Globe markers only appear for detected locations and move with the globe.
- Latest, Trending, World, Politics, Markets, Technology, Climate, and Saved screens load.

## Article Flow

Generate a fast article:

- Prompt: a current, well-covered topic.
- Mode: Fast.
- Expected: generated article with source links and `Quick edition`.

Generate a thorough article:

- Prompt: same or similar topic.
- Mode: Thorough.
- Expected: generated article with source links and `Consensus edition`.

Open a generated article by URL:

- Click/copy article link.
- Open it in a fresh tab.
- Expected: the same article loads from `/generated-articles/{id}`.

## Account Flow

- Sign up or log in through Supabase.
- Save an article.
- Like an article.
- Comment on an article.
- Like a comment.
- Open inbox.

Expected:

- User-specific calls succeed only when logged in.
- Notifications appear for article/comment interactions.
- Logged-out users can browse but cannot impersonate a `user_id`.

## Cold Start

Let Render sit idle long enough to sleep, or manually suspend/redeploy the service, then:

1. Open the Vercel app.
2. Generate an article.

Expected:

- UI stays in a waking/sourcing state instead of showing a broken screen.
- First request may take longer.
- No local/demo article is generated while `VITE_SIGNAL_API_URL` is configured.
