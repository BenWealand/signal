from __future__ import annotations

"""
X workflow HTTP surface.

All routes require SIGNAL_API_TOKEN.
Search + post/reply are live against the X API. Trends are not used;
discovery seeds recent search from Signal desk topics.
"""

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, validator

from app.api.routes_articles import (
    ARTICLE_RATE_LIMIT,
    MAX_LIMIT,
    _check_article_rate_limit,
    _client_rate_key,
    _require_signal_agent_token,
    _write_gemini_article,
)
from app.config import settings
from app.db import queries
from app.x.client import XApiError, XApiNotConfigured, get_x_client
from app.x.filter import filter_candidates
from app.x.models import XCandidate, XSharePackage
from app.x.pipeline import discover_candidates, maybe_share_package, run_x_pipeline
from app.x.reply import article_public_url, share_intent_url, x_reply_text

router = APIRouter()


class XPipelineRequest(BaseModel):
    max_articles: int = 3
    discover_limit: int = 10
    query: str = ""
    mode: str = "fast"
    limit: int = 12
    dry_run: bool | None = None
    auto_post: bool | None = None
    candidates: list[dict] = []

    @validator("max_articles")
    def max_articles_size(cls, value: int) -> int:
        return min(max(int(value or 1), 1), 5)

    @validator("discover_limit")
    def discover_size(cls, value: int) -> int:
        return min(max(int(value or 1), 1), 20)

    @validator("limit")
    def limit_size(cls, value: int) -> int:
        if value < 1 or value > MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        return value

    @validator("mode")
    def mode_value(cls, value: str) -> str:
        cleaned = (value or "fast").strip().lower()
        if cleaned not in {"fast", "thorough"}:
            raise ValueError("mode must be fast or thorough")
        return cleaned

    @validator("query")
    def query_size(cls, value: str) -> str:
        return (value or "").strip()[:240]


class XShareRequest(BaseModel):
    article_id: str = ""
    reply_text: str = ""
    post_id: str = ""
    trend_url: str = ""
    dry_run: bool | None = None


class XSearchRequest(BaseModel):
    query: str
    limit: int = 10

    @validator("query")
    def query_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("query is required")
        return cleaned[:240]

    @validator("limit")
    def limit_size(cls, value: int) -> int:
        return min(max(int(value or 1), 1), 20)


class XLookupRequest(BaseModel):
    url: str = ""
    post_id: str = ""

    @validator("url", "post_id")
    def trim(cls, value: str) -> str:
        return (value or "").strip()


@router.get("/agents/x/status")
def x_status(
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    client = get_x_client()
    return {
        "ok": True,
        "publicArticleBaseUrl": settings.public_article_base_url,
        "xClient": client.status(),
        "endpoints": {
            "status": "GET /agents/x/status",
            "trends": "GET /agents/x/trends",
            "search": "POST /agents/x/search",
            "lookup": "POST /agents/x/lookup",
            "articleReply": "POST /agents/x/article-reply",
            "run": "POST /agents/x/run",
            "share": "POST /agents/x/share",
        },
        "notes": [
            "Search, lookup, and post/reply call the live X API",
            "Trends API is not used — discovery seeds recent search from Signal desk topics",
            "Keep SIGNAL_X_DRY_RUN=true until you intentionally want live posts",
        ],
    }


@router.get("/agents/x/trends")
def x_trends(
    limit: int = 10,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    safe_limit = min(max(limit, 1), 20)
    candidates, provider = discover_candidates(limit=safe_limit, prefer_x=True)
    actionable = filter_candidates(candidates, limit=safe_limit)
    return {
        "provider": provider,
        "xClient": get_x_client().status(),
        "count": len(actionable),
        "candidates": [c.to_dict() for c in actionable],
        "rawCount": len(candidates),
    }


@router.post("/agents/x/search")
def x_search(
    payload: XSearchRequest,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    client = get_x_client()
    try:
        hits = client.search_recent(payload.query, limit=payload.limit)
        return {
            "provider": "x-api-search",
            "query": payload.query,
            "candidates": [c.to_dict() for c in hits],
        }
    except XApiNotConfigured as exc:
        candidate = XCandidate(
            topic=payload.query,
            prompt=payload.query,
            snippet=f"Manual/search fallback for query: {payload.query}",
            provider="query-fallback",
            source="x-agent",
            tag="x-trend",
        )
        return {
            "provider": "query-fallback",
            "query": payload.query,
            "warning": str(exc),
            "candidates": [candidate.to_dict()],
        }
    except XApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/agents/x/lookup")
def x_lookup(
    payload: XLookupRequest,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    """Resolve an X post URL or id into a pipeline candidate."""
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    if not payload.url and not payload.post_id:
        raise HTTPException(status_code=422, detail="Provide url or post_id")
    client = get_x_client()
    try:
        candidate = (
            client.candidate_from_url(payload.url)
            if payload.url
            else client.lookup_post(payload.post_id)
        )
    except XApiNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except XApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not candidate:
        raise HTTPException(status_code=404, detail="Post not found or URL not recognized")
    return {"provider": "x-api-lookup", "candidate": candidate.to_dict()}


@router.post("/agents/x/run")
def run_pipeline(
    request: Request,
    payload: XPipelineRequest,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    """
    Full automation loop:
    discover → filter → write → durable frontend link → share package / dry-run post.
    """
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    _check_article_rate_limit(_client_rate_key(request, "x-run"))

    manual: list[XCandidate] | None = None
    if payload.candidates:
        manual = []
        for row in payload.candidates[: payload.max_articles]:
            manual.append(
                XCandidate(
                    topic=str(row.get("topic") or row.get("trending_topic") or row.get("prompt") or "").strip(),
                    snippet=str(row.get("snippet") or ""),
                    prompt=str(row.get("prompt") or ""),
                    trend_url=str(row.get("trend_url") or row.get("trendUrl") or ""),
                    post_id=str(row.get("post_id") or row.get("postId") or ""),
                    author_handle=str(row.get("author_handle") or ""),
                    source=str(row.get("source") or "x-agent"),
                    tag=str(row.get("tag") or "x-trend"),
                    provider=str(row.get("provider") or "manual"),
                )
            )

    if payload.max_articles > ARTICLE_RATE_LIMIT:
        raise HTTPException(status_code=422, detail=f"max_articles must be <= {ARTICLE_RATE_LIMIT}")

    result = run_x_pipeline(
        max_articles=payload.max_articles,
        discover_limit=payload.discover_limit,
        query=payload.query,
        mode=payload.mode,
        source_limit=payload.limit,
        dry_run=payload.dry_run,
        auto_post=payload.auto_post,
        candidates=manual,
        write_fn=lambda prompt, limit, mode, build_id: _write_gemini_article(
            prompt, limit=limit, mode=mode, build_id=build_id
        ),
    )
    packages = []
    for pkg in result.get("packages") or []:
        packages.append(
            {
                **pkg,
                "articleUrl": pkg.get("article_url") or "",
                "replyText": pkg.get("reply_text") or "",
                "trendUrl": pkg.get("trend_url") or "",
                "intentUrl": (pkg.get("share") or {}).get("intentUrl") or share_intent_url(
                    pkg.get("article_url") or "",
                    (pkg.get("article") or {}).get("headline") or "",
                ),
            }
        )
    result["packages"] = packages
    return result


@router.post("/agents/x/share")
def share_existing(
    payload: XShareRequest,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    """Share an already-written article. Dry-run by default until X posting is implemented."""
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)

    article = None
    article_url = ""
    reply = (payload.reply_text or "").strip()
    if payload.article_id:
        article = queries.get_generated_article(payload.article_id)
        if not article:
            raise HTTPException(status_code=404, detail="Article not found")
        article_url = article_public_url(str(article["id"]))
        if not reply:
            reply = x_reply_text(article, article_url)

    if not reply:
        raise HTTPException(status_code=422, detail="Provide reply_text or article_id")

    package = XSharePackage(
        status="ready_to_post",
        article_url=article_url,
        reply_text=reply,
        trend_url=payload.trend_url,
        article=article or {},
        share={
            "postId": payload.post_id,
            "intentUrl": share_intent_url(article_url, (article or {}).get("headline") or ""),
        },
    )
    package = maybe_share_package(package, dry_run=payload.dry_run, auto_post=True)
    body = package.to_dict()
    return {
        "status": body["status"],
        "articleUrl": body.get("article_url") or "",
        "replyText": body.get("reply_text") or "",
        "share": body.get("share") or {},
        "error": body.get("error") or "",
    }
