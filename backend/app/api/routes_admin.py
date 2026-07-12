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
    _check_article_rate_limit,
    _client_rate_key,
    _write_gemini_article,
)
from app.auth import VALID_ROLES, public_user_view, require_admin_user
from app.config import settings
from app.db import queries
from app.x.client import XApiError, XApiNotConfigured, get_x_client
from app.x.filter import filter_candidates
from app.x.models import XCandidate
from app.x.pipeline import discover_candidates, run_x_pipeline
from app.x.reply import share_intent_url

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
    query: str = ""
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

    @validator("query")
    def query_size(cls, value: str) -> str:
        return (value or "").strip()[:240]

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

    result = run_x_pipeline(
        max_articles=payload.max_articles,
        discover_limit=payload.discover_limit,
        query=payload.query,
        mode=payload.mode,
        source_limit=payload.limit,
        dry_run=payload.dry_run,
        auto_post=payload.auto_post,
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
                ),
            }
        )
    result["packages"] = packages
    return result
