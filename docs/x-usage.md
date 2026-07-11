# Signal × X — In-Depth Usage Guide

This is the complete runbook for using X with Signal **without waiting on the X API**.
Everything in the loop already works today: discover → filter → write sourced article →
durable frontend link → share package. The only missing piece is live X HTTP calls, which
you plug into `backend/app/x/client.py`.

Canonical agent playbook for a single post: [`x-trend-agent.md`](./x-trend-agent.md).

---

## What Signal does vs what you add

| Step | Signal (built) | You (X API in backend) |
|------|----------------|------------------------|
| Find what's trending | `GET /agents/x/trends` — tries X client, else Signal desk topics | Implement `XClient.fetch_trending()` |
| Search a query | `POST /agents/x/search` — soft-falls back to the query itself | Implement `XClient.search_recent()` |
| Decide if it's worth covering | `app/x/filter.py` actionable filter + prompt blacklist | Optional: tighten filter rules |
| Write a sourced article | Gemini + news providers (not the tweet body) | — |
| Keep it on a frontend link | Postgres + `/?article=<id>` deep link | Set `PUBLIC_ARTICLE_BASE_URL` |
| Build reply / share text | `replyText` + `intentUrl` | — |
| Post / reply on X | Dry-run stub returns success without sending | Implement `XClient.post_tweet()` |

X/Twitter URLs are **never scraped as article sources** (`x.com` / `twitter.com` are blocked).
The post is a *topic trigger*; journalism comes from Bing / Guardian / GDELT / RSS / desk cache.

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

## How to automate (today, without X API)

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

Edit **only** `backend/app/x/client.py`:

1. `fetch_trending()` — map trends → `XCandidate(topic=..., snippet=..., provider="x-api")`
2. `search_recent(query)` — map tweets → candidates with `post_id`, `trend_url`, `snippet`
3. `post_tweet(text, in_reply_to_id=...)` — create tweet/reply; return `XPostResult`

Then:

```env
SIGNAL_X_DRY_RUN=false   # after post_tweet works
SIGNAL_X_AUTO_POST=true  # only if you want /run to publish automatically
```

Flip `XClient.status()["implemented"]` to `True` when bodies are real so `/agents/x/status` reflects it.

Suggested X endpoints (for your implementation notes):

- Trends: `GET /1.1/trends/place.json?id={woeid}` (bearer)
- Search: `GET /2/tweets/search/recent` (bearer)
- Post: `POST /2/tweets` (OAuth 1.0a user context)

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
