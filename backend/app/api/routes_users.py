from __future__ import annotations

from secrets import compare_digest

from pydantic import BaseModel, EmailStr, validator
from fastapi import APIRouter, Header, HTTPException, Request

from app.auth import (
    check_auth_rate_limit,
    decode_supabase_jwt,
    extract_bearer_token,
    public_user_view,
    supabase_auth_configured,
    sync_user_from_claims,
)
from app.config import settings
from app.db import queries


router = APIRouter()


class UserPayload(BaseModel):
    name: str = ""
    email: EmailStr | None = None
    plan: str = "Reader"
    supabase_user_id: str | None = None

    @validator("name")
    def name_size(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) > 120:
            raise ValueError("name must be 120 characters or fewer")
        return cleaned


class ProfileUpdatePayload(BaseModel):
    name: str

    @validator("name")
    def name_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) < 2:
            raise ValueError("name must be at least 2 characters")
        if len(cleaned) > 120:
            raise ValueError("name must be 120 characters or fewer")
        return cleaned


class SaveStoryPayload(BaseModel):
    user_id: int | None = None
    story_id: str
    title: str
    source_count: int = 0


class HistoryPayload(BaseModel):
    user_id: int | None = None
    session_id: str | None = None
    action_type: str
    topic: str | None = None
    section: str | None = None
    prompt: str | None = None
    article_id: str | None = None


class ArticleLikePayload(BaseModel):
    user_id: int | None = None
    session_id: str | None = None
    actor_name: str = "Reader"


class ArticleCommentPayload(BaseModel):
    user_id: int | None = None
    session_id: str | None = None
    author_name: str = "Reader"
    body: str
    parent_comment_id: int | None = None


class CommentLikePayload(BaseModel):
    user_id: int | None = None
    session_id: str | None = None
    actor_name: str = "Reader"


def _extract_bearer_token(authorization: str) -> str:
    return extract_bearer_token(authorization)


def _user_id_from_supabase_jwt(authorization: str) -> int | None:
    if not supabase_auth_configured():
        return None
    claims = decode_supabase_jwt(authorization)
    user = sync_user_from_claims(claims, touch_login=False)
    if not user:
        raise HTTPException(status_code=401, detail="Authenticated user is not registered")
    return int(user["id"])


def _require_user_route_guard(user_id: int | None, x_signal_token: str = "", authorization: str = "") -> int | None:
    if supabase_auth_configured() and extract_bearer_token(authorization):
        jwt_user_id = _user_id_from_supabase_jwt(authorization)
        if user_id is not None and int(user_id) != jwt_user_id:
            raise HTTPException(status_code=403, detail="Authenticated user does not match requested user")
        return jwt_user_id

    # Prefer JWT when auth is configured even if token missing — force auth for user-scoped ids.
    if supabase_auth_configured() and user_id is not None:
        jwt_user_id = _user_id_from_supabase_jwt(authorization)
        if int(user_id) != jwt_user_id:
            raise HTTPException(status_code=403, detail="Authenticated user does not match requested user")
        return jwt_user_id

    expected = getattr(settings, "signal_api_token", "").strip()
    if user_id is None:
        return None
    if not expected:
        raise HTTPException(status_code=503, detail="User route authentication is not configured")
    supplied = (x_signal_token or _extract_bearer_token(authorization)).strip()
    if not supplied or not compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="User route access requires authentication")
    return user_id


@router.post("/users")
def upsert_user(
    request: Request,
    payload: UserPayload,
    authorization: str = Header(default=""),
):
    """
    Secure session sync: requires a valid Supabase JWT.
    Email / supabase_user_id are taken from the token, not the client body.
    """
    check_auth_rate_limit(f"users-upsert:{request.client.host if request.client else 'unknown'}", limit=30)
    claims = decode_supabase_jwt(authorization)
    token_sub = str(claims.get("sub") or "")
    if payload.supabase_user_id and payload.supabase_user_id != token_sub:
        raise HTTPException(status_code=403, detail="supabase_user_id does not match authenticated user")
    user = sync_user_from_claims(
        claims,
        name_override=payload.name or None,
        touch_login=True,
    )
    return public_user_view(user)


@router.get("/users/me")
def current_user(authorization: str = Header(default="")):
    claims = decode_supabase_jwt(authorization)
    user = sync_user_from_claims(claims, touch_login=False)
    return public_user_view(user)


@router.patch("/users/me")
def update_current_user(payload: ProfileUpdatePayload, authorization: str = Header(default="")):
    claims = decode_supabase_jwt(authorization)
    user = sync_user_from_claims(claims, name_override=payload.name, touch_login=False)
    return public_user_view(user)


@router.get("/users/{user_id}/saved")
def saved_for_user(user_id: int, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    auth_user_id = _require_user_route_guard(user_id, x_signal_token=x_signal_token, authorization=authorization)
    return queries.list_saved_stories(auth_user_id)


@router.get("/users/{user_id}/preferences/auto")
def auto_preferences(user_id: int, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    auth_user_id = _require_user_route_guard(user_id, x_signal_token=x_signal_token, authorization=authorization)
    return queries.get_auto_preferences(user_id=auth_user_id)


@router.post("/history")
def record_history(payload: HistoryPayload, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    auth_user_id = _require_user_route_guard(payload.user_id, x_signal_token=x_signal_token, authorization=authorization)
    queries.record_history(
        user_id=auth_user_id,
        session_id=payload.session_id,
        action_type=payload.action_type,
        topic=payload.topic,
        section=payload.section,
        prompt=payload.prompt,
        article_id=payload.article_id,
    )
    return {"ok": True}


@router.post("/saved-stories")
def save_story(payload: SaveStoryPayload, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    auth_user_id = _require_user_route_guard(payload.user_id, x_signal_token=x_signal_token, authorization=authorization)
    saved_id = queries.save_story(auth_user_id, payload.story_id, payload.title, payload.source_count)
    return {"id": saved_id, "ok": True}


@router.get("/articles/{article_id}/social")
def article_social(
    article_id: str,
    user_id: int | None = None,
    session_id: str | None = None,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    auth_user_id = _require_user_route_guard(user_id, x_signal_token=x_signal_token, authorization=authorization) if user_id else None
    return queries.get_article_social(article_id, user_id=auth_user_id, session_id=session_id)


@router.post("/articles/{article_id}/likes")
def like_article(
    article_id: str,
    payload: ArticleLikePayload,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    auth_user_id = _require_user_route_guard(payload.user_id, x_signal_token=x_signal_token, authorization=authorization) if payload.user_id else None
    return queries.like_article(article_id, auth_user_id, payload.session_id, payload.actor_name)


@router.post("/articles/{article_id}/comments")
def add_comment(
    article_id: str,
    payload: ArticleCommentPayload,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    auth_user_id = _require_user_route_guard(payload.user_id, x_signal_token=x_signal_token, authorization=authorization) if payload.user_id else None
    return queries.add_article_comment(
        article_id,
        payload.body,
        auth_user_id,
        payload.session_id,
        payload.author_name,
        payload.parent_comment_id,
    )


@router.post("/comments/{comment_id}/likes")
def like_comment(
    comment_id: int,
    payload: CommentLikePayload,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    auth_user_id = _require_user_route_guard(payload.user_id, x_signal_token=x_signal_token, authorization=authorization) if payload.user_id else None
    return queries.like_comment(comment_id, auth_user_id, payload.session_id, payload.actor_name)


@router.get("/users/{user_id}/notifications")
def user_notifications(user_id: int, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    auth_user_id = _require_user_route_guard(user_id, x_signal_token=x_signal_token, authorization=authorization)
    return queries.list_notifications(auth_user_id)


@router.post("/users/{user_id}/notifications/read")
def mark_user_notifications_read(user_id: int, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    auth_user_id = _require_user_route_guard(user_id, x_signal_token=x_signal_token, authorization=authorization)
    queries.mark_notifications_read(auth_user_id)
    return {"ok": True}
