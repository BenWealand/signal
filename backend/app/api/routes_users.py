from __future__ import annotations

from secrets import compare_digest

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


def _extract_bearer_token(authorization: str) -> str:
    prefix = "Bearer "
    if authorization.startswith(prefix):
        return authorization[len(prefix):].strip()
    return ""


def _require_user_route_guard(user_id: int | None, x_signal_token: str = "", authorization: str = "") -> None:
    """
    TODO(auth): Replace this shared agent-token guard with Supabase JWT validation
    and derive user_id server-side. Until then, production deployments that set
    SIGNAL_API_TOKEN fail closed for user-specific data routes.
    """
    expected = settings.signal_api_token.strip()
    if not expected:
        return
    supplied = (x_signal_token or _extract_bearer_token(authorization)).strip()
    if not supplied or not compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="User route access requires authentication")


@router.post("/users")
def upsert_user(payload: UserPayload):
    return queries.upsert_user(payload.name, payload.email, payload.plan, payload.supabase_user_id)


@router.get("/users/{user_id}/saved")
def saved_for_user(user_id: int, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    _require_user_route_guard(user_id, x_signal_token=x_signal_token, authorization=authorization)
    return queries.list_saved_stories(user_id)


@router.get("/users/{user_id}/preferences/auto")
def auto_preferences(user_id: int, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    _require_user_route_guard(user_id, x_signal_token=x_signal_token, authorization=authorization)
    return queries.get_auto_preferences(user_id=user_id)


@router.post("/history")
def record_history(payload: HistoryPayload, x_signal_token: str = Header(default=""), authorization: str = Header(default="")):
    _require_user_route_guard(payload.user_id, x_signal_token=x_signal_token, authorization=authorization)
    queries.record_history(
        user_id=payload.user_id,
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
    _require_user_route_guard(payload.user_id, x_signal_token=x_signal_token, authorization=authorization)
    saved_id = queries.save_story(payload.user_id, payload.story_id, payload.title, payload.source_count)
    return {"id": saved_id, "ok": True}
