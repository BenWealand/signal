from __future__ import annotations

import re
import time
import uuid
import logging
import threading
from collections import defaultdict, deque
from secrets import compare_digest
from urllib.parse import urlencode

from pydantic import BaseModel, validator
from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.db import queries
from app.config import settings
from app.policy.prompt_filter import prompt_is_blocked
from app.processing.article_writer import (
    GeminiArticleUnavailable,
    write_article_from_prompt,
    get_build_progress,
    set_build_progress,
)


router = APIRouter()
logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 2_000
MAX_SNIPPET_CHARS = 1_000
MAX_LIMIT = 50
ARTICLE_RATE_LIMIT = 5
ARTICLE_RATE_WINDOW_SECONDS = 60.0
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


class TrendArticleRequest(BaseModel):
    prompt: str
    source: str = "news-desk"
    trend_url: str = ""
    tag: str = "trend"
    limit: int = 12
    mode: str = "fast"
    user_id: int | None = None
    async_mode: bool = False

    @validator("prompt")
    def prompt_size(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("prompt is required")
        if len(value) > MAX_PROMPT_CHARS:
            raise ValueError(f"prompt must be {MAX_PROMPT_CHARS} characters or fewer")
        return value

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


class FollowUpRequest(BaseModel):
    prompt: str = ""
    headline: str = ""
    dek: str = ""
    body: list[str] = []
    limit: int = 5

    @validator("prompt", "headline", "dek")
    def follow_up_text_size(cls, value: str) -> str:
        if len(value or "") > MAX_PROMPT_CHARS:
            raise ValueError(f"text fields must be {MAX_PROMPT_CHARS} characters or fewer")
        return (value or "").strip()

    @validator("limit")
    def follow_up_limit(cls, value: int) -> int:
        return min(max(value, 1), 8)


class XTrendArticleRequest(BaseModel):
    prompt: str = ""
    snippet: str = ""
    trending_topic: str = ""
    trend_url: str = ""
    source: str = "x-agent"
    tag: str = "x-trend"
    limit: int = 12
    mode: str = "fast"

    @validator("prompt", "trending_topic")
    def short_text_size(cls, value: str) -> str:
        if len(value or "") > MAX_PROMPT_CHARS:
            raise ValueError(f"text fields must be {MAX_PROMPT_CHARS} characters or fewer")
        return (value or "").strip()

    @validator("snippet")
    def snippet_size(cls, value: str) -> str:
        if len(value or "") > MAX_SNIPPET_CHARS:
            raise ValueError(f"snippet must be {MAX_SNIPPET_CHARS} characters or fewer")
        return (value or "").strip()

    @validator("limit")
    def limit_size(cls, value: int) -> int:
        if value < 1 or value > MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
        return value


def _client_rate_key(request: Request, endpoint: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    host = forwarded or (request.client.host if request.client else "unknown")
    return f"{endpoint}:{host}"


def _check_article_rate_limit(key: str, now: float | None = None) -> None:
    now = now or time.monotonic()
    bucket = _rate_buckets[key]
    while bucket and now - bucket[0] > ARTICLE_RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= ARTICLE_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Article generation rate limit exceeded")
    bucket.append(now)


def _extract_bearer_token(authorization: str) -> str:
    prefix = "Bearer "
    if authorization.startswith(prefix):
        return authorization[len(prefix):].strip()
    return ""


def _require_signal_agent_token(x_signal_token: str = "", authorization: str = "") -> None:
    expected = settings.signal_api_token.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Signal agent access is not configured")
    supplied = (x_signal_token or _extract_bearer_token(authorization)).strip()
    if not supplied or not compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid Signal agent token")


def _clean_social_text(text: str, max_chars: int = 420) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:max_chars].rstrip()


def _reject_blocked_prompt(prompt: str) -> None:
    match = prompt_is_blocked(prompt)
    if match.blocked:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "prompt_blocked",
                "message": "This prompt is blocked by the Signal prompt filter.",
                "source": match.source,
            },
        )


def _write_gemini_article(prompt: str, *, limit: int, mode: str, build_id: str) -> dict:
    started = time.monotonic()
    try:
        article = write_article_from_prompt(prompt, limit=limit, mode=mode, build_id=build_id)
        logger.info(
            "Gemini article generated",
            extra={
                "build_id": build_id,
                "mode": mode,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "source_count": article.get("sourceCount", 0),
                "prompt_length": len(prompt or ""),
            },
        )
        return article
    except GeminiArticleUnavailable as exc:
        logger.warning(
            "Gemini article unavailable",
            extra={
                "build_id": build_id,
                "mode": mode,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "prompt_length": len(prompt or ""),
                "reason": str(exc),
            },
        )
        raise HTTPException(
            status_code=503,
            detail={
                "code": "gemini_article_unavailable",
                "message": str(exc) or "Gemini could not write an article from the available sources.",
            },
        ) from exc


def _resolve_optional_owner_user_id(user_id: int | None, authorization: str = "") -> int | None:
    if user_id is None:
        return None
    try:
        from app.api.routes_users import _require_user_route_guard
        return _require_user_route_guard(user_id, authorization=authorization)
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Owner user auth check failed", extra={"user_id": user_id})
        raise HTTPException(status_code=401, detail="Article owner requires authentication") from exc


def _prompt_from_x_payload(payload: XTrendArticleRequest) -> str:
    prompt = _clean_social_text(payload.prompt, 240)
    topic = _clean_social_text(payload.trending_topic, 120)
    snippet = _clean_social_text(payload.snippet, 280)
    parts = []
    if prompt:
        parts.append(prompt)
    if topic and topic.lower() not in prompt.lower():
        parts.append(f"Trending topic: {topic}")
    if snippet and snippet.lower() not in " ".join(parts).lower():
        parts.append(f"Social post snippet: {snippet}")
    combined = ". ".join(parts).strip(". ")
    if not combined:
        raise HTTPException(status_code=422, detail="Provide prompt, trending_topic, or snippet")
    return combined


def article_public_url(article_id: str) -> str:
    base = settings.public_article_base_url.strip().rstrip("/")
    query = urlencode({"article": article_id})
    return f"{base}/?{query}" if base else f"/?{query}"


def x_reply_text(article: dict, article_url: str) -> str:
    headline = _clean_social_text(article.get("headline", "Signal article"), 180)
    suffix = f"Read the sourced Signal write-up: {article_url}"
    text = f"{headline}\n\n{suffix}"
    if len(text) <= 260:
        return text
    return f"{headline[: max(40, 256 - len(suffix))].rstrip()}...\n\n{suffix}"


_FOLLOW_UP_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "is", "was",
    "at", "to", "from", "with", "by", "that", "this", "it", "its", "be",
    "are", "were", "has", "have", "had", "as", "new", "will", "more",
    "said", "says", "about", "after", "over", "into", "also", "than",
    "what", "how", "why", "latest", "update", "updates", "news",
})


def _follow_up_topic(payload: FollowUpRequest) -> str:
    """Compress the prompt/headline into a short natural topic phrase."""
    source = payload.prompt or payload.headline or ""
    words = [w for w in re.findall(r"[A-Za-z0-9'&.-]+", source) if w.lower() not in _FOLLOW_UP_STOPWORDS]
    if not words:
        words = source.split()
    return " ".join(words[:6]).strip() or "this story"


def _editorial_follow_ups(payload: FollowUpRequest, limit: int) -> list[str]:
    """
    Exploration angles used when the LLM is unavailable. Each opens a
    genuinely different direction instead of rewording the original prompt.
    """
    topic = _follow_up_topic(payload)
    angles = [
        f"who is most affected by {topic}",
        f"economic impact of {topic}",
        f"history and background of {topic}",
        f"government and policy response to {topic}",
        f"opposing views on {topic}",
        f"what happens next with {topic}",
        f"how {topic} compares around the world",
        f"key players behind {topic}",
    ]
    return angles[:limit]


@router.post("/articles/follow-ups")
def article_follow_ups(payload: FollowUpRequest):
    """
    Follow-up search recommendations for the article reader.
    Prefers LLM-generated exploration angles; falls back to editorial angles.
    """
    limit = min(max(payload.limit, 1), 8)
    try:
        from app.llm.gemini_writer import suggest_follow_up_prompts_with_gemini
        llm_prompts = suggest_follow_up_prompts_with_gemini(
            topic=payload.prompt,
            headline=payload.headline,
            dek=payload.dek,
            body_paragraphs=payload.body[:6],
            max_prompts=limit,
        )
    except Exception:
        llm_prompts = None
    if llm_prompts:
        return {"prompts": llm_prompts[:limit], "source": "llm"}
    return {"prompts": _editorial_follow_ups(payload, limit), "source": "editorial"}


@router.get("/articles/progress")
def article_build_progress(
    build_id: str | None = Query(default=None, alias="buildId"),
    build_id_legacy: str | None = Query(default=None, alias="build_id"),
):
    """Real-time build progress for the article generation pipeline."""
    return get_build_progress(build_id or build_id_legacy)


@router.get("/articles/test-gemini")
def test_gemini():
    """Quick diagnostic — makes one minimal Gemini call and returns the result."""
    from app.llm.gemini_writer import get_last_gemini_error, write_article_with_gemini
    result = write_article_with_gemini(
        "test",
        [{
            "source_name": "Test",
            "title": "Signal diagnostic test",
            "raw_text": (
                "This diagnostic source says Signal is checking whether the Gemini API "
                "can generate a short neutral article from supplied source material. "
                "The response should mention only this test and avoid adding outside facts."
            ),
        }],
    )
    return {
        "gemini_key_set": bool(settings.gemini_api_key),
        "model": settings.gemini_model,
        "result": result,
        "success": result is not None,
        "error": None if result else get_last_gemini_error(),
    }


@router.get("/articles/{article_id}")
def article_detail(article_id: int):
    article = queries.get_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.get("/articles/source/{source_name}")
def articles_for_source(source_name: str):
    return queries.articles_by_source(source_name)


@router.get("/sources")
def sources(active_only: bool = False):
    return queries.list_sources(active_only=active_only)


@router.get("/generated-articles")
def generated_articles(limit: int = 25):
    return queries.list_generated_articles(limit=limit)


@router.get("/generated-articles/{article_id}")
def generated_article(article_id: str):
    article = queries.get_generated_article(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Generated article not found")
    return article


@router.post("/generated-articles/purge-blocked")
def purge_blocked_generated_articles(
    limit: int = 1000,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    return queries.purge_blacklisted_generated_articles(limit=min(max(limit, 1), 5000))


@router.post("/generated-articles/purge-legacy")
def purge_legacy_generated_articles(
    limit: int = 1000,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    return queries.purge_legacy_generated_articles(limit=min(max(limit, 1), 5000))


@router.post("/articles/generate-from-trend")
def generate_from_trend(
    request: Request,
    payload: TrendArticleRequest,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    _check_article_rate_limit(_client_rate_key(request, "generate-from-trend"))
    _reject_blocked_prompt(payload.prompt)
    build_id = f"build-{uuid.uuid4().hex}"
    article = _write_gemini_article(payload.prompt, limit=payload.limit, mode=payload.mode, build_id=build_id)
    article["buildId"] = build_id
    article["source"] = payload.source
    article["trendUrl"] = payload.trend_url
    article["tag"] = payload.tag
    article["ownerUserId"] = _resolve_optional_owner_user_id(payload.user_id, authorization)
    queries.save_generated_article(article)
    return article


@router.post("/agents/x/article-reply")
def generate_x_article_reply(
    request: Request,
    payload: XTrendArticleRequest,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    _check_article_rate_limit(_client_rate_key(request, "x-article-reply"))
    prompt = _prompt_from_x_payload(payload)
    _reject_blocked_prompt(prompt)
    build_id = f"build-{uuid.uuid4().hex}"
    article = _write_gemini_article(prompt, limit=payload.limit, mode=payload.mode, build_id=build_id)
    article["buildId"] = build_id
    article["source"] = payload.source
    article["trendUrl"] = payload.trend_url
    article["tag"] = payload.tag
    article["ownerUserId"] = None
    queries.save_generated_article(article)
    article_url = article_public_url(str(article["id"]))
    return {
        "status": "ready_to_post",
        "article": article,
        "articleUrl": article_url,
        "replyText": x_reply_text(article, article_url),
        "trendUrl": payload.trend_url,
    }


@router.post("/articles/write")
def write_article(request: Request, payload: TrendArticleRequest, authorization: str = Header(default="")):
    _check_article_rate_limit(_client_rate_key(request, "write"))
    _reject_blocked_prompt(payload.prompt)
    build_id = f"build-{uuid.uuid4().hex}"
    owner_user_id = _resolve_optional_owner_user_id(payload.user_id, authorization)

    if not payload.async_mode:
        article = _write_gemini_article(payload.prompt, limit=payload.limit, mode=payload.mode, build_id=build_id)
        article["buildId"] = build_id
        article["ownerUserId"] = owner_user_id
        queries.save_generated_article(article)
        return article

    set_build_progress(
        build_id,
        active=True,
        prompt=payload.prompt,
        stage="fetching",
        stage_label="Queued for sourcing...",
        sources_found=0,
        sources_enriched=0,
        claims_extracted=0,
        draft_text="",
        draft_headline="",
        article=None,
        error=None,
        started_at=time.time(),
    )

    def _job() -> None:
        try:
            article = _write_gemini_article(
                payload.prompt,
                limit=payload.limit,
                mode=payload.mode,
                build_id=build_id,
            )
            article["buildId"] = build_id
            article["ownerUserId"] = owner_user_id
            queries.save_generated_article(article)
            set_build_progress(
                build_id,
                active=False,
                stage="done",
                stage_label="Done",
                article=article,
                draft_text="\n\n".join(article.get("body") or []),
                draft_headline=article.get("headline") or "",
                error=None,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            message = str(detail.get("message") or detail)
            set_build_progress(
                build_id,
                active=False,
                stage="error",
                stage_label="Write failed",
                error=message,
                article=None,
            )
        except Exception as exc:
            logger.exception("Async article write failed", extra={"build_id": build_id})
            set_build_progress(
                build_id,
                active=False,
                stage="error",
                stage_label="Write failed",
                error=str(exc) or "Article write failed",
                article=None,
            )

    threading.Thread(target=_job, daemon=True, name=f"article-write-{build_id[:10]}").start()
    return {"buildId": build_id, "status": "building", "active": True}
