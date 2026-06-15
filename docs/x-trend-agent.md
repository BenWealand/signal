# X Trend Article Agent Workflow

This document tells an agent how to turn an X/Twitter post snippet or trending topic into a sourced Signal article, then reply with the already-written article link.

## Goal

When a public X post or trend is worth covering:

1. Extract the useful topic signal from the post or trend.
2. Ask Signal to write and save a sourced article.
3. Post a reply that links to the saved article.

Do not publish a link until the Signal API returns `status: "ready_to_post"`.

## Required Configuration

The Signal backend must have:

```env
SIGNAL_API_TOKEN=long-random-secret
PUBLIC_ARTICLE_BASE_URL=https://your-public-signal-site.example
```

The agent must send the token on every request:

```text
Authorization: Bearer long-random-secret
```

or:

```text
X-Signal-Token: long-random-secret
```

If the backend returns `401`, the token is missing or wrong. If it returns `503`, agent access is not configured on the backend.

## Endpoint

```http
POST /agents/x/article-reply
Content-Type: application/json
Authorization: Bearer <SIGNAL_API_TOKEN>
```

Local development URL:

```text
http://127.0.0.1:8000/agents/x/article-reply
```

## Request Payload

Use whichever fields are available. At least one of `prompt`, `trending_topic`, or `snippet` is required.

```json
{
  "prompt": "optional explicit topic to investigate",
  "trending_topic": "#ExampleTrend",
  "snippet": "Short excerpt from the public X post or trend context.",
  "trend_url": "https://x.com/example/status/123",
  "source": "x-agent",
  "tag": "x-trend",
  "limit": 12,
  "mode": "fast"
}
```

Recommended defaults:

```json
{
  "source": "x-agent",
  "tag": "x-trend",
  "limit": 12,
  "mode": "fast"
}
```

Use `mode: "fast"` for reply workflows. Use a slower mode only when a human explicitly asks for a deeper article and latency is acceptable.

## Example Request

```bash
curl -X POST http://127.0.0.1:8000/agents/x/article-reply \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SIGNAL_API_TOKEN" \
  -d '{
    "trending_topic": "#BudgetVote",
    "snippet": "Lawmakers are posting competing claims about an overnight budget vote.",
    "trend_url": "https://x.com/example/status/123",
    "source": "x-agent",
    "tag": "x-trend",
    "limit": 12,
    "mode": "fast"
  }'
```

## Response Contract

Successful responses look like:

```json
{
  "status": "ready_to_post",
  "articleUrl": "https://your-public-signal-site.example/?article=write-1780006577982",
  "replyText": "Headline...\n\nRead the sourced Signal write-up: https://your-public-signal-site.example/?article=write-1780006577982",
  "trendUrl": "https://x.com/example/status/123",
  "article": {
    "id": "write-1780006577982",
    "headline": "Generated headline",
    "sourceCount": 12,
    "sources": []
  }
}
```

Post `replyText` as the X reply. The `articleUrl` opens the exact generated article through the frontend deep link.

## Agent Decision Rules

Only send a request when the post or trend has enough context to form a news query. Good inputs include:

- A named person, organization, place, policy, product, event, or incident.
- A claim that can be checked against public reporting.
- A trend with enough words to identify the subject.

Do not send requests for:

- Private personal information.
- Harassment, doxxing, or instructions to target a person.
- Vague reactions with no factual topic, such as "this is wild" without context.
- Content that mainly asks the agent to invent unsupported claims.

## Posting Rules

Before replying on X:

1. Confirm `status` is `ready_to_post`.
2. Confirm `articleUrl` is present.
3. Prefer the returned `replyText` exactly.
4. Do not add claims that are not in the returned article.
5. If adding custom wording, keep it neutral and attribute the link as a sourced Signal write-up.

Safe reply pattern:

```text
Signal checked this against public source coverage and wrote a sourced summary:
<articleUrl>
```

## Error Handling

| Status | Meaning | Agent action |
| --- | --- | --- |
| `401` | Missing or invalid token | Stop and refresh credentials. |
| `503` | Backend has no `SIGNAL_API_TOKEN` configured | Stop and ask an operator to configure secure access. |
| `422` | Missing usable `prompt`, `trending_topic`, or `snippet` | Retry with a clearer topic or snippet. |
| `5xx` | Backend, database, or source fetch failure | Retry later; do not post a link. |

## Verification Checklist

Before running the agent unattended:

- `GET /health` returns `ok: true`.
- `POST /agents/x/article-reply` with a valid token returns `ready_to_post`.
- The returned `articleUrl` opens in a browser.
- A request without a token returns `401`.
- `PUBLIC_ARTICLE_BASE_URL` points to the public frontend, not localhost, in production.

