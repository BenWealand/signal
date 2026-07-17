from __future__ import annotations

"""
Admin-only routes (Supabase JWT + email allowlist).

Default admin: benwealand@gmail.com (SIGNAL_ADMIN_EMAILS).
Proxies X agent operations so the browser never needs SIGNAL_API_TOKEN.
"""

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, validator

from app.api.routes_articles import (
    ARTICLE_RATE_LIMIT,
    MAX_LIMIT,
    MAX_PROMPT_CHARS,
    _check_article_rate_limit,
    _client_rate_key,
    _write_gemini_article,
)
from app.auth import VALID_ROLES, public_user_view, require_admin_user
from app.config import settings
from app.db import queries
from app.x.client import XApiError, XApiNotConfigured, get_x_client, status_id_from_url
from app.x.filter import filter_candidates
from app.x.models import XCandidate
from app.x.pipeline import discover_candidates, run_x_pipeline
from app.x.reply import article_public_url, share_intent_url, x_reply_text

router = APIRouter()


def _require_admin(authorization: str = "") -> dict:
    return require_admin_user(authorization)


class AdminRolePayload(BaseModel):
    role: str

    @validator("role")
    def role_value(cls, value: str) -> str:
        cleaned = (value or "").strip().lower()
        if cleaned not in VALID_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return cleaned


class AdminSearchRequest(BaseModel):
    query: str
    limit: int = 8

    @validator("query")
    def query_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("query is required")
        return cleaned[:240]

    @validator("limit")
    def limit_size(cls, value: int) -> int:
        return min(max(int(value or 1), 1), 20)


class AdminRunRequest(BaseModel):
    max_articles: int = 1
    discover_limit: int = 8
    prompt: str = ""
    query: str = ""
    reply_url: str = ""
    mode: str = "fast"
    limit: int = 10
    dry_run: bool = True
    auto_post: bool = False

    @validator("max_articles")
    def max_articles_size(cls, value: int) -> int:
        return min(max(int(value or 1), 1), 3)

    @validator("mode")
    def mode_value(cls, value: str) -> str:
        cleaned = (value or "fast").strip().lower()
        if cleaned not in {"fast", "thorough"}:
            raise ValueError("mode must be fast or thorough")
        return cleaned

    @validator("prompt")
    def prompt_size(cls, value: str) -> str:
        return (value or "").strip()[:MAX_PROMPT_CHARS]

    @validator("query")
    def query_size(cls, value: str) -> str:
        return (value or "").strip()[:240]

    @validator("reply_url")
    def reply_url_size(cls, value: str) -> str:
        return (value or "").strip()[:500]

    @validator("limit")
    def limit_size(cls, value: int) -> int:
        if value < 1 or value > MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        return value


class AdminLookupRequest(BaseModel):
    url: str = ""
    post_id: str = ""

    @validator("url", "post_id")
    def trim(cls, value: str) -> str:
        return (value or "").strip()


class AdminFeedShareRequest(BaseModel):
    article_id: str
    dry_run: bool = True
    reply_url: str = ""

    @validator("article_id")
    def article_id_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("article_id is required")
        return cleaned[:160]

    @validator("reply_url")
    def reply_url_size(cls, value: str) -> str:
        return (value or "").strip()[:500]


def _reply_post_id(reply_url: str) -> str:
    if not reply_url:
        return ""
    post_id = status_id_from_url(reply_url)
    if not post_id:
        raise HTTPException(status_code=422, detail="Reply URL must be a valid x.com or twitter.com post URL")
    return post_id


@router.get("/admin/me")
def admin_me(authorization: str = Header(default="")):
    user = _require_admin(authorization)
    view = public_user_view(user)
    return {
        "admin": True,
        "email": view.get("email"),
        "name": view.get("name"),
        "id": view.get("id"),
        "role": view.get("role"),
        "permissions": view.get("permissions"),
    }


@router.get("/admin/users")
def admin_list_users(
    limit: int = 50,
    offset: int = 0,
    authorization: str = Header(default=""),
):
    _require_admin(authorization)
    rows = queries.list_users(limit=limit, offset=offset)
    return {
        "total": queries.count_users(),
        "limit": min(max(int(limit or 50), 1), 200),
        "offset": max(int(offset or 0), 0),
        "users": [public_user_view(row) for row in rows],
    }


@router.patch("/admin/users/{user_id}/role")
def admin_set_user_role(
    user_id: int,
    payload: AdminRolePayload,
    authorization: str = Header(default=""),
):
    admin = _require_admin(authorization)
    if int(admin["id"]) == int(user_id) and payload.role != "admin":
        raise HTTPException(status_code=400, detail="Admins cannot demote their own account")
    updated = queries.set_user_role(user_id, payload.role)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return public_user_view(updated)


@router.get("/admin/x/status")
def admin_x_status(authorization: str = Header(default="")):
    user = _require_admin(authorization)
    client = get_x_client()
    return {
        "ok": True,
        "adminEmail": user.get("email"),
        "publicArticleBaseUrl": settings.public_article_base_url,
        "xClient": client.status(),
        "dryRunDefault": bool(settings.x_dry_run),
        "autoPostDefault": bool(settings.x_auto_post),
        "notes": [
            "Admin terminal uses your signed-in session (no SIGNAL_API_TOKEN in the browser)",
            "Keep SIGNAL_X_DRY_RUN=true until you intentionally want live posts",
            "Trends API is unused — discovery seeds X search from Signal desk topics",
        ],
    }


@router.get("/admin/x/trends")
def admin_x_trends(limit: int = 8, authorization: str = Header(default="")):
    _require_admin(authorization)
    safe_limit = min(max(limit, 1), 20)
    candidates, provider = discover_candidates(limit=safe_limit, prefer_x=True)
    actionable = filter_candidates(candidates, limit=safe_limit)
    return {
        "provider": provider,
        "count": len(actionable),
        "candidates": [c.to_dict() for c in actionable],
        "rawCount": len(candidates),
        "xClient": get_x_client().status(),
    }


@router.post("/admin/x/search")
def admin_x_search(payload: AdminSearchRequest, authorization: str = Header(default="")):
    _require_admin(authorization)
    client = get_x_client()
    try:
        hits = client.search_recent(payload.query, limit=payload.limit)
        return {
            "provider": "x-api-search",
            "query": payload.query,
            "candidates": [c.to_dict() for c in hits],
        }
    except XApiNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except XApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/admin/x/lookup")
def admin_x_lookup(payload: AdminLookupRequest, authorization: str = Header(default="")):
    _require_admin(authorization)
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


@router.post("/admin/x/run")
def admin_x_run(
    request: Request,
    payload: AdminRunRequest,
    authorization: str = Header(default=""),
):
    _require_admin(authorization)
    _check_article_rate_limit(_client_rate_key(request, "admin-x-run"))
    if payload.max_articles > ARTICLE_RATE_LIMIT:
        raise HTTPException(status_code=422, detail=f"max_articles must be <= {ARTICLE_RATE_LIMIT}")

    direct_prompt = payload.prompt or payload.query
    manual_candidates: list[XCandidate] | None = None
    reply_post_id = _reply_post_id(payload.reply_url)
    if reply_post_id and direct_prompt:
        manual_candidates = [
            XCandidate(
                topic=direct_prompt,
                prompt=direct_prompt,
                trend_url=payload.reply_url,
                post_id=reply_post_id,
                source="x-agent",
                tag="x-reply",
                provider="manual-prompt",
            )
        ]
    elif reply_post_id:
        try:
            linked = get_x_client().lookup_post(reply_post_id)
        except XApiNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except XApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not linked:
            raise HTTPException(status_code=404, detail="The linked X post could not be loaded")
        linked.trend_url = payload.reply_url
        manual_candidates = [linked]

    result = run_x_pipeline(
        max_articles=payload.max_articles,
        discover_limit=payload.discover_limit,
        direct_prompt="" if manual_candidates else direct_prompt,
        mode=payload.mode,
        source_limit=payload.limit,
        dry_run=payload.dry_run,
        auto_post=payload.auto_post,
        candidates=manual_candidates,
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
                "intentUrl": (pkg.get("share") or {}).get("intentUrl")
                or share_intent_url(
                    pkg.get("article_url") or "",
                    (pkg.get("article") or {}).get("headline") or "",
                    reply_text=pkg.get("reply_text") or "",
                    in_reply_to_id=str((pkg.get("candidate") or {}).get("post_id") or ""),
                ),
            }
        )
    result["packages"] = packages
    return result


@router.get("/admin/x/feed-drafts")
def admin_x_feed_drafts(
    hours: int = 24,
    limit: int = 100,
    authorization: str = Header(default=""),
):
    """Draft X posts for unique Gemini articles currently visible in the feeds."""
    _require_admin(authorization)
    safe_hours = min(max(int(hours or 24), 1), 168)
    safe_limit = min(max(int(limit or 100), 1), 200)
    articles = queries.list_recent_x_feed_articles(hours=safe_hours, limit=safe_limit)
    drafts = []
    for article in articles:
        url = article_public_url(str(article["id"]))
        text = x_reply_text(article, url)
        drafts.append(
            {
                "articleId": article["id"],
                "headline": article.get("headline") or "Signal article",
                "section": article.get("section") or "latest",
                "createdAt": article.get("createdAt"),
                "sourceCount": article.get("sourceCount") or 0,
                "articleUrl": url,
                "replyText": text,
                "intentUrl": share_intent_url(url, article.get("headline") or "", reply_text=text),
                "xShare": article.get("xShare") or {"posted": False},
            }
        )
    return {
        "hours": safe_hours,
        "count": len(drafts),
        "unposted": sum(1 for item in drafts if not item["xShare"].get("posted")),
        "drafts": drafts,
    }


@router.post("/admin/x/feed-share")
def admin_x_feed_share(
    payload: AdminFeedShareRequest,
    authorization: str = Header(default=""),
):
    """Post one stored feed article; successful live shares are idempotent."""
    _require_admin(authorization)
    article = queries.get_generated_article(payload.article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    if article.get("generation_mode") not in {"fast", "thorough"}:
        raise HTTPException(status_code=422, detail="Only Gemini feed articles can be posted")

    existing = queries.get_posted_x_share(payload.article_id)
    if existing and not payload.dry_run:
        return {
            "status": "already_posted",
            "articleId": payload.article_id,
            "postId": existing.get("x_post_id") or "",
            "postUrl": existing.get("x_post_url") or "",
            "replyToPostId": existing.get("reply_to_post_id") or "",
            "replyUrl": existing.get("reply_url") or "",
            "message": "This article has already been posted to X.",
        }

    url = article_public_url(str(article["id"]))
    text = x_reply_text(article, url)
    reply_post_id = _reply_post_id(payload.reply_url)
    client = get_x_client()
    result = (
        client.reply_to_post(reply_post_id, text, dry_run=payload.dry_run)
        if reply_post_id
        else client.post_tweet(text, dry_run=payload.dry_run)
    )
    share_status = "posted" if result.posted else "dry_run" if result.dry_run and result.ok else "failed"
    queries.record_x_article_share(
        payload.article_id,
        text,
        status=share_status,
        x_post_id=result.post_id,
        x_post_url=result.post_url,
        reply_to_post_id=reply_post_id,
        reply_url=payload.reply_url,
        error="" if result.ok else result.message,
    )
    return {
        "status": share_status,
        "articleId": payload.article_id,
        "articleUrl": url,
        "replyText": text,
        "postId": result.post_id,
        "postUrl": result.post_url,
        "replyToPostId": reply_post_id,
        "replyUrl": payload.reply_url,
        "message": result.message,
    }
