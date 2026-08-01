from __future__ import annotations

import re
import time
import uuid
import logging
from collections import defaultdict, deque
from secrets import compare_digest

from pydantic import BaseModel, validator
from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.db import queries
from app.config import settings
from app.policy.prompt_filter import prompt_is_blocked
from app.processing.article_writer import get_build_progress, set_build_progress


from app.x.models import XCandidate
from app.x.pipeline import maybe_share_package, write_article_for_candidate
from app.x.reply import article_public_url, build_prompt, x_reply_text


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
    post_id: str = ""
    source: str = "x-agent"
    tag: str = "x-trend"
    limit: int = 12
    mode: str = "fast"
    auto_post: bool | None = None
    dry_run: bool | None = None

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

    @validator("mode")
    def mode_value(cls, value: str) -> str:
        cleaned = (value or "fast").strip().lower()
        if cleaned not in {"fast", "thorough"}:
            raise ValueError("mode must be fast or thorough")
        return cleaned


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


def _is_specific_x_prompt(prompt: str) -> bool:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'&.-]*", prompt or "")
    if len(words) >= 4:
        return True
    if len(words) >= 3 and len(prompt) >= 24:
        return True
    return False


def _prompt_from_x_payload(payload: XTrendArticleRequest) -> str:
    prompt = re.sub(r"\s+", " ", payload.prompt or "").strip()[:240].rstrip()
    if prompt and _is_specific_x_prompt(prompt):
        return prompt
    try:
        return build_prompt(payload.trending_topic, payload.snippet, payload.prompt)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# article_public_url and x_reply_text are imported from app.x.reply above
# and re-exported for tests / callers that historically used routes_articles.


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
    Uses deterministic editorial templates so generation capacity stays reserved
    for complete articles.
    """
    limit = min(max(payload.limit, 1), 8)
    return {"prompts": _editorial_follow_ups(payload, limit), "source": "editorial"}


@router.get("/articles/progress")
def article_build_progress(
    build_id: str | None = Query(default=None, alias="buildId"),
    build_id_legacy: str | None = Query(default=None, alias="build_id"),
):
    """Real-time build progress for the article generation pipeline."""
    return get_build_progress(build_id or build_id_legacy)


@router.get("/articles/test-zen")
def test_zen():
    """Deprecated route name for the website Gemini-writer diagnostic."""
    from app.llm.article_generator import generate_article_package
    source_text = (
        "Signal is checking whether Gemini can generate a neutral sourced "
        "article from supplied source material without adding outside facts. "
    ) * 5
    try:
        result = generate_article_package(
            "Signal Gemini writer diagnostic",
            [
                {
                    "source_name": "Diagnostic A",
                    "title": "Signal tests Gemini article generation",
                    "url": "https://example.com/diagnostic-a",
                    "raw_text": source_text,
                },
                {
                    "source_name": "Diagnostic B",
                    "title": "Independent diagnostic confirms Gemini writer test",
                    "url": "https://example.org/diagnostic-b",
                    "raw_text": source_text,
                },
                {
                    "source_name": "Diagnostic C",
                    "title": "Gemini writer diagnostic uses bounded source material",
                    "url": "https://example.net/diagnostic-c",
                    "raw_text": source_text,
                },
                {
                    "source_name": "Diagnostic D",
                    "title": "Schema-constrained article generation diagnostic",
                    "url": "https://iana.org/help/diagnostic-d",
                    "raw_text": source_text,
                },
            ],
            mode="fast",
        )
        error = None
    except Exception as exc:
        result = None
        error = str(exc)
    return {
        "provider": "gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "model": settings.gemini_model,
        "result": result,
        "success": result is not None,
        "error": error,
    }


@router.get("/articles/test-gemini")
def test_gemini_alias():
    """Website Gemini-writer diagnostic (legacy implementation name)."""
    return test_zen()


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


@router.post("/articles/generate-from-trend", status_code=202)
def generate_from_trend(
    request: Request,
    payload: TrendArticleRequest,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    _check_article_rate_limit(_client_rate_key(request, "generate-from-trend"))
    _reject_blocked_prompt(payload.prompt)
    owner_user_id = _resolve_optional_owner_user_id(payload.user_id, authorization)
    job = queries.enqueue_article_generation_job(
        payload.prompt,
        mode=payload.mode,
        priority=10,
        payload={
            "limit": payload.limit,
            "source": payload.source,
            "trendUrl": payload.trend_url,
            "tag": payload.tag,
            "ownerUserId": owner_user_id,
        },
    )
    return {"buildId": job["id"], "status": job["status"], "active": job["status"] != "saved"}


@router.post("/agents/x/article-reply", status_code=202)
def generate_x_article_reply(
    request: Request,
    payload: XTrendArticleRequest,
    x_signal_token: str = Header(default=""),
    authorization: str = Header(default=""),
):
    _require_signal_agent_token(x_signal_token=x_signal_token, authorization=authorization)
    _check_article_rate_limit(_client_rate_key(request, "x-article-reply"))
    candidate = XCandidate(
        topic=payload.trending_topic or payload.prompt,
        snippet=payload.snippet,
        prompt=payload.prompt,
        trend_url=payload.trend_url,
        post_id=payload.post_id,
        source=payload.source,
        tag=payload.tag,
        provider="manual",
    )

    # Enrich from X when a post URL/id is given but snippet/topic is thin.
    if (payload.trend_url or payload.post_id) and (not candidate.snippet or not candidate.topic):
        try:
            from app.x.client import get_x_client

            client = get_x_client()
            looked = (
                client.candidate_from_url(payload.trend_url)
                if payload.trend_url
                else client.lookup_post(payload.post_id)
            )
            if looked:
                candidate.topic = candidate.topic or looked.topic
                candidate.snippet = candidate.snippet or looked.snippet
                candidate.prompt = candidate.prompt or looked.prompt
                candidate.post_id = candidate.post_id or looked.post_id
                candidate.trend_url = candidate.trend_url or looked.trend_url
                candidate.author_handle = looked.author_handle
                candidate.provider = "x-api-lookup"
        except Exception:
            logger.info("X lookup enrichment skipped for article-reply", exc_info=True)

    prompt_seed = re.sub(r"\s+", " ", candidate.prompt or "").strip()[:240].rstrip()
    if prompt_seed and _is_specific_x_prompt(prompt_seed):
        prompt = prompt_seed
    else:
        try:
            prompt = build_prompt(candidate.topic, candidate.snippet, candidate.prompt)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    _reject_blocked_prompt(prompt)
    job = queries.enqueue_article_generation_job(
        prompt,
        mode=payload.mode,
        priority=80,
        payload={
            "limit": payload.limit,
            "source": payload.source,
            "trendUrl": candidate.trend_url,
            "tag": payload.tag,
            "xPostId": candidate.post_id,
            "sourcePolicy": "x_response",
            "xSource": {
                "url": candidate.trend_url,
                "text": candidate.snippet or candidate.topic,
                "authorHandle": candidate.author_handle,
            },
        },
    )
    return {
        "buildId": job["id"],
        "status": job["status"],
        "active": job["status"] not in {"saved", "failed"},
        "trendUrl": candidate.trend_url,
        "candidate": candidate.to_dict(),
    }


@router.post("/articles/write", status_code=202)
def write_article(request: Request, payload: TrendArticleRequest, authorization: str = Header(default="")):
    _check_article_rate_limit(_client_rate_key(request, "write"))
    _reject_blocked_prompt(payload.prompt)
    owner_user_id = _resolve_optional_owner_user_id(payload.user_id, authorization)
    job = queries.enqueue_article_generation_job(
        payload.prompt,
        mode=payload.mode,
        priority=100,
        payload={
            "limit": payload.limit,
            "source": payload.source,
            "trendUrl": payload.trend_url,
            "tag": payload.tag,
            "ownerUserId": owner_user_id,
        },
    )
    return {
        "buildId": job["id"],
        "status": job["status"],
        "active": job["status"] not in {"saved", "failed"},
    }
