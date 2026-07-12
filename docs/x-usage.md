# Signal × X — In-Depth Usage Guide

This is the complete runbook for using X with Signal **without waiting on the X API**.
Everything in the loop already works today: discover → filter → write sourced article →
durable frontend link → share package. The only missing piece is live X HTTP calls, which
you plug into `backend/app/x/client.py`.

Canonical agent playbook for a single post: [`x-trend-agent.md`](./x-trend-agent.md).

---

## What Signal does vs what you add

| Step | Signal (built) | You (config) |
|------|----------------|--------------|
| Find posts | Recent search + desk-topic seeding (`POST /agents/x/search`, `/run`) | Set `X_API_BEARER_TOKEN` |
| Resolve a post URL | `POST /agents/x/lookup` | Bearer token |
| Decide if it's worth covering | `app/x/filter.py` + prompt blacklist | Optional: tighten filter |
| Write a sourced article | Gemini + news providers (not the tweet body) | `GEMINI_API_KEY` |
| Keep it on a frontend link | Postgres + `/?article=<id>` | `PUBLIC_ARTICLE_BASE_URL` |
| Build reply / share text | `replyText` + `intentUrl` | — |
| Post / reply on X | Live OAuth 1.0a `post_tweet` (dry-run by default) | Write tokens + `SIGNAL_X_DRY_RUN` |

Trends API is **not** used. X/Twitter URLs are never scraped as article sources.

---

## Architecture

```text
                    ┌─────────────────────────────┐
                    │  POST /agents/x/run         │
                    │  (or article-reply / share) │
                    └──────────────┬──────────────┘
                                   │
         ┌─────────────────────────┼─────────────────────────┐
         ▼                         ▼                         ▼
  app/x/client.py            app/x/filter.py           app/x/pipeline.py
  (STUB → your X API)        actionable topics         write + package
         │                         │                         │
         └─────────────────────────┴────────────► Gemini write
                                                         │
                                                         ▼
                                              generated_articles (Postgres)
                                                         │
                                                         ▼
                              PUBLIC_ARTICLE_BASE_URL/?article=write-...
                                                         │
                                                         ▼
                                              replyText + intentUrl
                                                         │
                                                         ▼
                                              XClient.post_tweet (stub / your API)
```

### Key files

| File | Role |
|------|------|
| `backend/app/x/client.py` | **Implement X API here** |
| `backend/app/x/pipeline.py` | Full orchestration |
| `backend/app/x/filter.py` | Skip vague / blocked topics |
| `backend/app/x/reply.py` | Prompt merge, public URL, reply text, intent URL |
| `backend/app/api/routes_x.py` | status / trends / search / run / share |
| `backend/app/api/routes_articles.py` | `POST /agents/x/article-reply` (single topic) |

---

## Required environment (Render)

```env
# Already required for agents
SIGNAL_API_TOKEN=long-random-secret
PUBLIC_ARTICLE_BASE_URL=https://signal-mocha-three.vercel.app
GEMINI_API_KEY=...
DATABASE_URL=...

# X credentials — set these when you wire the API (optional until then)
X_API_BEARER_TOKEN=
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_TOKEN_SECRET=
X_TRENDS_WOEID=1

# Safety switches (recommended defaults)
SIGNAL_X_DRY_RUN=true
SIGNAL_X_AUTO_POST=false
```

Auth on every `/agents/x/*` call:

```http
Authorization: Bearer <SIGNAL_API_TOKEN>
```

or `X-Signal-Token: <SIGNAL_API_TOKEN>`.

---

## Endpoints

Base URL example: `https://signal-54jh.onrender.com`

### 1. Status — `GET /agents/x/status`

Confirms token, public base URL, and whether X read/write credentials are present.

```bash
curl -sS "$API/agents/x/status" -H "Authorization: Bearer $SIGNAL_API_TOKEN" | jq
```

### 2. Trends — `GET /agents/x/trends?limit=10`

- If `fetch_trending()` is implemented → X trends
- Else → Signal-internal entities / topics (`provider: "signal-internal"`)

```bash
curl -sS "$API/agents/x/trends?limit=8" -H "Authorization: Bearer $SIGNAL_API_TOKEN" | jq
```

### 3. Search — `POST /agents/x/search`

```bash
curl -sS -X POST "$API/agents/x/search" \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"budget vote congress","limit":5}' | jq
```

Until search is implemented, returns a single `query-fallback` candidate so the rest of the loop still runs.

### 4. Single article — `POST /agents/x/article-reply`

Use when you already have a specific post/trend.

```bash
curl -sS -X POST "$API/agents/x/article-reply" \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "trending_topic": "#BudgetVote",
    "snippet": "Lawmakers are posting competing claims about an overnight budget vote.",
    "trend_url": "https://x.com/example/status/123",
    "post_id": "123",
    "mode": "fast",
    "limit": 12
  }'
```

Success shape:

```json
{
  "status": "ready_to_post",
  "articleUrl": "https://signal-mocha-three.vercel.app/?article=write-...",
  "replyText": "Headline...\n\nRead the sourced Signal write-up: https://...",
  "trendUrl": "https://x.com/example/status/123",
  "share": { "intentUrl": "https://x.com/intent/tweet?...", "dry_run": true },
  "article": { "id": "write-...", "headline": "...", "sourceCount": 8 }
}
```

**Do not share until `status` is `ready_to_post` (or `shared`).**

### 5. Full automation — `POST /agents/x/run`

Discovers topics, filters, writes up to `max_articles`, returns share packages.

```bash
curl -sS -X POST "$API/agents/x/run" \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "max_articles": 2,
    "discover_limit": 10,
    "mode": "fast",
    "limit": 10,
    "dry_run": true,
    "auto_post": false
  }'
```

Or pass explicit candidates (skip discovery):

```bash
curl -sS -X POST "$API/agents/x/run" \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "max_articles": 1,
    "candidates": [{
      "topic": "Federal Reserve rate decision",
      "snippet": "Markets react to overnight comments from the Fed chair.",
      "trend_url": "https://x.com/example/status/456",
      "post_id": "456"
    }]
  }'
```

### 6. Share existing — `POST /agents/x/share`

```bash
curl -sS -X POST "$API/agents/x/share" \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"article_id":"write-1780006577982","post_id":"123","dry_run":true}'
```

---

## Frontend permanence

Every successful write saves to Postgres `generated_articles` with id `write-<unix_ms>`.

Public link:

```text
https://<PUBLIC_ARTICLE_BASE_URL>/?article=write-<id>
```

Opening that URL on Vercel loads the SPA, reads `?article=`, and fetches
`GET /generated-articles/<id>` from Render. The article also becomes eligible for
`/news/trending` once it accrues views/likes/comments.

Manual share from the article UI: **Share on X** opens the intent URL (no API).

---

## Admin UI terminal

Signed in as `benwealand@gmail.com`, open **Settings** to use the **X API usage terminal**:

- Status / Discover / Search / Run agent (dry-run)
- Calls `/admin/x/*` with your Supabase session (no token in the browser)

Backend allowlist: `SIGNAL_ADMIN_EMAILS` (default `benwealand@gmail.com`).
Frontend mirror: `VITE_SIGNAL_ADMIN_EMAILS` (optional; defaults to the same email).

## How to run the agent (ops)

### A) From Settings (admin)

1. Sign in as `benwealand@gmail.com`
2. Open Settings → X API usage terminal
3. Click **Run agent** (dry-run)

### B) CLI / curl

```bash
export API=https://signal-54jh.onrender.com
export SIGNAL_API_TOKEN=...

curl -sS "$API/awake" >/dev/null
curl -sS -X POST "$API/agents/x/run" \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_articles":1,"dry_run":true}'
```

Or: `npm run x:pipeline`

### C) GitHub Action

`.github/workflows/x-trend-pipeline.yml` — needs `SIGNAL_API_URL` + `SIGNAL_API_TOKEN` secrets.

### Option A — GitHub Action (included)

Workflow: `.github/workflows/x-trend-pipeline.yml`

1. Wakes the backend (`GET /awake`)
2. Calls `POST /agents/x/run` with `dry_run: true`
3. Logs `articleUrl` / `replyText` for each package

Secrets: `SIGNAL_API_URL`, `SIGNAL_API_TOKEN`.

### Option B — CLI

```bash
npm run x:pipeline
# or with a forced topic:
npm run x:pipeline -- --topic "Senate budget vote overnight"
```

### Option C — External agent / cron

Wake → `POST /agents/x/run` → for each package with `status=ready_to_post`,
post `replyText` however you like (manual review queue, Zapier, or your X client once live).

Recommended cadence while dry-running: every 2–6 hours, `max_articles: 1` or `2`.
Respect the write rate limit (**5 / minute / IP**).

---

## Plugging in the X API

Search, lookup, and post/reply are **implemented** in `backend/app/x/client.py`.

Trends (`fetch_trending`) are intentionally **not** used. Discovery instead:

1. Uses your `query` with X recent search, or
2. Takes Signal desk topics and runs X recent search for each, or
3. Falls back to desk topics alone if X search is unavailable

### Env on Render

```env
X_API_BEARER_TOKEN=...          # search / lookup
X_API_KEY=...                   # consumer key
X_API_SECRET=...                # consumer secret
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
SIGNAL_X_DRY_RUN=true           # keep true until you want live posts
SIGNAL_X_AUTO_POST=false
```

To publish for real:

```env
SIGNAL_X_DRY_RUN=false
SIGNAL_X_AUTO_POST=true   # only if /run should post automatically
```

---

## Decision rules (built-in filter)

**Cover when** the topic has a named entity, hashtag, or newsy keywords
(vote, court, market, storm, budget, …), or ≥4 clear words.

**Skip when** too short, vague reactions (“this is wild”), or prompt-blacklist hits.

Agents should still apply human judgment before unattended auto-post.

---

## Verification checklist

1. `GET /health` → ok
2. `GET /agents/x/status` with token → `ok: true`, `publicArticleBaseUrl` set
3. `GET /agents/x/trends` → candidates (internal or X)
4. `POST /agents/x/article-reply` → `ready_to_post` + working `articleUrl` in a browser
5. `POST /agents/x/run` with `dry_run: true` → packages logged, nothing posted
6. Request without token → `401`
7. After you implement posting: one manual `POST /agents/x/share` with `dry_run: false` before enabling auto-post

---

## Error reference

| Status | Meaning |
|--------|---------|
| `401` | Bad / missing `SIGNAL_API_TOKEN` |
| `503` | Agent token not configured on backend, or Gemini write unavailable |
| `422` | Blocked / skipped / invalid payload |
| `429` | Rate limit (5 writes / min / IP) |
| Package `status: skipped\|blocked\|error` | Topic filtered or write failed — do not share |
| Package `share.dry_run: true` | Post was simulated — safe |

---

## End-to-end happy path (copy/paste)

```bash
export API=https://signal-54jh.onrender.com
export SIGNAL_API_TOKEN=...   # same secret as Render

curl -sS "$API/awake" >/dev/null

curl -sS -X POST "$API/agents/x/run" \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_articles":1,"mode":"fast","dry_run":true}' \
  | jq '.packages[] | {status, articleUrl, replyText}'
```

Open each `articleUrl`, confirm the article, then share `replyText` (or enable real posting once `post_tweet` is implemented).
