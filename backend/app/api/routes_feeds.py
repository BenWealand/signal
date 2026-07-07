from __future__ import annotations

from fastapi import APIRouter, Response

from app import cache
from app.config import settings
from app.db import queries

router = APIRouter()


def _cache_ttl() -> float:
    return float(max(15, settings.feed_cache_ttl_seconds))


@router.get("/feeds/bootstrap")
def feeds_bootstrap(
    response: Response,
    latest_limit: int = 25,
    story_limit: int = 20,
    trending_limit: int = 18,
    section_limit: int = 18,
    topics_limit: int = 10,
):
    cache_key = (
        f"bootstrap:{latest_limit}:{story_limit}:{trending_limit}:"
        f"{section_limit}:{topics_limit}"
    )
    payload = cache.get_or_set(
        cache_key,
        _cache_ttl(),
        lambda: queries.bootstrap_feeds(
            latest_limit=min(max(latest_limit, 1), 50),
            story_limit=min(max(story_limit, 1), 50),
            trending_limit=min(max(trending_limit, 1), 50),
            section_limit=min(max(section_limit, 1), 50),
            topics_limit=min(max(topics_limit, 1), 30),
        ),
    )
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    return payload