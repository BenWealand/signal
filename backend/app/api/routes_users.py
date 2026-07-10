from __future__ import annotations

from secrets import compare_digest

try:
    import jwt
except ImportError:  # pragma: no cover - deploy installs PyJWT from requirements.
    jwt = None
from pydantic import BaseModel, EmailStr
from fastapi import APIRouter, Header, HTTPException

from app.config import settings
from app.db import queries


router = APIRouter()


class UserPayload(BaseModel):
    name: str
    email: EmailStr
    plan: str = "Reader"
    supabase_user_id: str | None = None


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
    prefix = "Bearer "
    if authorization.startswith(prefix):
        return authorization[len(prefix):].strip()
    return ""


def _user_id_from_supabase_jwt(authorization: str) -> int | None:
    secret = getattr(settings, "supabase_jwt_secret", "").strip()
    if not secret:
        return None
    if jwt is None:
        raise HTTPException(status_code=503, detail="JWT authentication dependency is not installed")
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
    except jwt.InvalidAudienceError:
        payload = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid authentication token") from exc
    subject = str(payload.get("sub") or "")
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    user = queries.get_user_by_supabase_id(subject)
    if not user:
        raise HTTPException(status_code=401, detail="Authenticated user is not registered")
    return int(user["id"])


def _require_user_route_guard(user_id: int | None, x_signal_token: str = "", authorization: str = "") -> int | None:
    jwt_user_id = _user_id_from_supabase_jwt(authorization)
    if jwt_user_id is not None:
        if user_id is not None and int(user_id) != jwt_user_id:
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
def upsert_user(payload: UserPayload):
    return queries.upsert_user(payload.name, payload.email, payload.plan, payload.supabase_user_id)


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
