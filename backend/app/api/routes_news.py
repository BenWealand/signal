from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks, Header

from app import cache
from app.config import settings
from app.db import queries
from app.db.connection import get_connection
from app.processing.article_writer import write_article_from_prompt
from app.ingest.rss_ingest import fetch_section_rss, fetch_all_rss_fast, SECTION_FEEDS
from app.observability import log_event

logger = logging.getLogger(__name__)

SECTION_PROMPTS: dict[str, str] = {
    "world": "international diplomacy conflict global affairs",
    "politics": "congress senate legislation government policy",
    "sporks": "sports athletics leagues championships olympic games",
    "markets": "stock market economy financial inflation interest rates",
    "technology": "artificial intelligence semiconductor technology cybersecurity",
    "climate": "climate change environment renewable energy weather",
}

SECTION_SLUGS = tuple(SECTION_PROMPTS)

router = APIRouter()


def _story_key(item: dict) -> str:
    text = (
        item.get("headline")
        or item.get("topic_label")
        or item.get("prompt")
        or item.get("summary")
        or ""
    )
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return " ".join(words[:14])


_STORY_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "what", "will",
    "says", "said", "into", "over", "after", "before", "about", "home",
    "today", "new", "news",
}


def _story_tokens(item: dict) -> set[str]:
    text = _story_key(item)
    return {
        word
        for word in re.findall(r"[a-z0-9]+", text)
        if len(word) > 2 and word not in _STORY_STOPWORDS
    }


def _is_duplicate_story(a: dict, b: dict) -> bool:
    a_tokens = _story_tokens(a)
    b_tokens = _story_tokens(b)
    if not a_tokens or not b_tokens:
        return False
    overlap = len(a_tokens & b_tokens)
    smaller = min(len(a_tokens), len(b_tokens))
    return overlap >= 4 or (overlap >= 3 and overlap / smaller >= 0.38)


def _dedupe_stories(items: list[dict], limit: int) -> list[dict]:
    deduped: list[dict] = []
    for item in items:
        if not _story_key(item):
            continue
        duplicate_index = next((i for i, current in enumerate(deduped) if _is_duplicate_story(item, current)), None)
        if duplicate_index is None:
            deduped.append(item)
            continue
        current = deduped[duplicate_index]
        item_sources = item.get("sourceCount") or item.get("source_count") or item.get("article_count") or 0
        current_sources = current.get("sourceCount") or current.get("source_count") or current.get("article_count") or 0
        item_date = item.get("createdAt") or item.get("created_at") or item.get("updated_at") or ""
        current_date = current.get("createdAt") or current.get("created_at") or current.get("updated_at") or ""
        if (item_date, item_sources) > (current_date, current_sources):
            deduped[duplicate_index] = item
    return deduped[:limit]


@router.get("/news/{section}")
def section_news(section: str, limit: int = 20):
    """
    Return content for a section page, merging two sources:
    1. Generated articles (from write_article_from_prompt) matching section keywords — richest content
    2. Story clusters matching section keywords — fallback when generated articles are sparse
    """
    slug = section.lower().replace(" ", "-")

    generated = _dedupe_stories(queries.list_generated_articles_by_section(slug, limit=limit * 3), limit)

    # If we have enough generated articles, return them directly
    if len(generated) >= max(1, limit // 2):
        return generated[:limit]

    # Supplement with story clusters
    clusters = queries.list_stories_by_section(slug, limit=limit * 2)
    return _dedupe_stories(generated + clusters, limit)


@router.post("/news/refresh/{section}")
def refresh_section(section: str, background_tasks: BackgroundTasks):
    slug = section.lower().replace(" ", "-")
    background_tasks.add_task(_generate_fast_section_articles, slug)
    return {"ok": True, "section": section, "status": "fetching"}


@router.get("/news/trending-topics")
def trending_topics(limit: int = 12):
    return cache.get_or_set(
        f"trending-topics:{limit}",
        float(max(15, settings.feed_cache_ttl_seconds)),
        lambda: queries.list_trending_topics(limit=min(max(limit, 1), 30)),
    )


@router.get("/news/trending")
def trending_articles(limit: int = 18):
    safe_limit = min(max(limit, 1), 50)
    return cache.get_or_set(
        f"trending:{safe_limit}",
        float(max(15, settings.feed_cache_ttl_seconds)),
        lambda: queries.list_trending_generated_articles(limit=safe_limit),
    )


@router.post("/ingest/rss")
def ingest_all_rss(background_tasks: BackgroundTasks):
    """Trigger a full RSS refresh across all sections (runs in background)."""
    background_tasks.add_task(_run_full_rss_ingest)
    return {"ok": True, "feeds": len(__import__("app.ingest.rss_ingest", fromlist=["ALL_FEEDS"]).ALL_FEEDS), "status": "fetching"}


@router.post("/ingest/daily")
def ingest_daily(
    background_tasks: BackgroundTasks,
    x_signal_token: str = Header(default="", alias="X-Signal-Token"),
    authorization: str = Header(default=""),
):
    """
    Daily desk refresh: pull fresh RSS into Postgres so Fast mode can
    answer from cache. Protected by SIGNAL_API_TOKEN.
    """
    from secrets import compare_digest
    from fastapi import HTTPException

    expected = (settings.signal_api_token or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Signal agent access is not configured")
    supplied = (x_signal_token or "").strip()
    if authorization.lower().startswith("bearer "):
        supplied = supplied or authorization[7:].strip()
    if not supplied or not compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid Signal agent token")

    def _job() -> None:
        try:
            from app.main import run_daily_source_refresh
            run_daily_source_refresh(synthesize_sections=True)
        except Exception:
            log_event(logger, "daily_ingest_endpoint_failed", level=logging.ERROR)
            logger.exception("Daily ingest endpoint failed")

    background_tasks.add_task(_job)
    return {"ok": True, "status": "fetching", "mode": "daily"}


@router.post("/ingest/rss/{section}")
def ingest_section_rss(section: str, background_tasks: BackgroundTasks, enrich: bool = True):
    """Trigger RSS refresh for one section with optional full-text enrichment."""
    slug = section.lower().replace(" ", "-")
    if slug not in SECTION_FEEDS:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown section: {slug}. Valid: {list(SECTION_FEEDS)}")
    background_tasks.add_task(_run_section_rss_ingest, slug, enrich)
    return {"ok": True, "section": slug, "enrich": enrich, "status": "fetching"}


@router.get("/ingest/rss/status")
def rss_status():
    """Return a count of articles by source to show feed health."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_name, COUNT(*) AS article_count,
                       MAX(created_at) AS latest
                FROM articles
                WHERE rss_url IS NOT NULL
                GROUP BY source_name
                ORDER BY article_count DESC
                LIMIT 30
                """
            )
            rows = [queries.row_to_dict(r) for r in cur.fetchall()]
    return {"sources": rows, "total": sum(r["article_count"] for r in rows)}


def _section_prompts(section: str, count: int) -> list[str]:
    slug = section.lower().replace(" ", "-")
    base = SECTION_PROMPTS.get(slug, slug.replace("-", " "))
    candidates = queries.list_section_generation_prompts(slug, limit=count * 4)
    candidates.extend([
        f"{base} latest developments",
        f"{base} breaking updates",
        f"{base} policy and public impact",
    ])
    prompts: list[str] = []
    seen: set[str] = set()
    for prompt in candidates:
        cleaned = " ".join(str(prompt).strip().split())
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        prompts.append(cleaned)
        if len(prompts) >= count:
            break
    return prompts


def _generate_fast_section_articles(section: str, count: int | None = None) -> None:
    """Generate shared fast-mode section articles and save them to the DB."""
    slug = section.lower().replace(" ", "-")
    if slug not in SECTION_PROMPTS:
        return
    target_count = max(1, min(count or settings.section_fast_articles_per_refresh, 5))
    generated = 0
    for prompt in _section_prompts(slug, target_count * 3):
        if queries.generated_prompt_exists_recent(prompt, settings.section_fast_min_age_minutes):
            continue
        try:
            article = write_article_from_prompt(prompt, limit=10, use_gemini=True, mode="fast")
            article["section"] = slug
            article["source"] = "Signal desk"
            article["tag"] = "fast-draft"
            queries.save_generated_article(article)
            generated += 1
            if generated >= target_count:
                break
        except Exception:
            log_event(logger, "section_fast_generation_failed", level=logging.ERROR, section=slug, prompt=prompt)
            logger.exception("Background fast section article generation failed")
    cache.invalidate("bootstrap:")
    cache.invalidate(f"trending:")
    cache.invalidate(f"trending-topics:")


def _run_full_rss_ingest() -> None:
    try:
        from app.main import _ingest_and_enrich
        articles = fetch_all_rss_fast(max_per_section=12)
        _ingest_and_enrich(articles)
    except Exception:
        log_event(logger, "full_rss_ingest_failed", level=logging.ERROR)
        logger.exception("Full RSS ingest task failed")


def _run_section_rss_ingest(section: str, enrich: bool) -> None:
    try:
        from app.main import _ingest_and_enrich
        articles = fetch_section_rss(section, enrich=enrich, max_articles=40)
        _ingest_and_enrich(articles)
    except Exception:
        log_event(logger, "section_rss_ingest_failed", level=logging.ERROR, section=section, enrich=enrich)
        logger.exception("Section RSS ingest task failed")
