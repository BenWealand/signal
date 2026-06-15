from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks

from app.db import queries
from app.db.connection import get_connection
from app.processing.article_writer import write_article_from_prompt
from app.ingest.rss_ingest import fetch_section_rss, fetch_all_rss_fast, SECTION_FEEDS

logger = logging.getLogger(__name__)

SECTION_PROMPTS: dict[str, str] = {
    "world": "international diplomacy conflict global affairs",
    "politics": "congress senate legislation government policy",
    "markets": "stock market economy financial inflation interest rates",
    "technology": "artificial intelligence semiconductor technology cybersecurity",
    "climate": "climate change environment renewable energy weather",
    "source-wire": "breaking news wire services latest",
}

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
    prompt = SECTION_PROMPTS.get(slug, slug.replace("-", " "))
    background_tasks.add_task(_fetch_section, prompt)
    return {"ok": True, "section": section, "status": "fetching"}


@router.get("/news/trending-topics")
def trending_topics(limit: int = 12):
    """
    Return trending topics. Primary source: entity co-occurrence across recent articles.
    Fallback 1: story cluster titles with source counts.
    Fallback 2: top articles ordered by recency/source.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Primary: named entities mentioned by 2+ articles in last 72h
            cur.execute(
                """
                SELECT entity_text, entity_type, COUNT(*) AS mentions
                FROM entities
                WHERE created_at > NOW() - INTERVAL '72 hours'
                  AND LENGTH(entity_text) > 2
                GROUP BY entity_text, entity_type
                HAVING COUNT(*) >= 2
                ORDER BY mentions DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            if rows:
                return [queries.row_to_dict(r) for r in rows]

            # Fallback 1: entity mentions regardless of threshold
            cur.execute(
                """
                SELECT entity_text, entity_type, COUNT(*) AS mentions
                FROM entities
                WHERE created_at > NOW() - INTERVAL '72 hours'
                  AND LENGTH(entity_text) > 3
                GROUP BY entity_text, entity_type
                ORDER BY mentions DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            if rows:
                return [queries.row_to_dict(r) for r in rows]

            # Fallback 2: story clusters with member counts
            cur.execute(
                """
                SELECT sc.topic_label AS entity_text,
                       'topic'::text  AS entity_type,
                       COUNT(sca.article_id) AS mentions
                FROM story_clusters sc
                JOIN story_cluster_articles sca ON sca.story_cluster_id = sc.id
                GROUP BY sc.id, sc.topic_label
                ORDER BY mentions DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            if rows:
                return [queries.row_to_dict(r) for r in rows]

            # Fallback 3: most recent article titles as topics
            cur.execute(
                """
                SELECT title AS entity_text,
                       source_name AS entity_type,
                       1 AS mentions
                FROM articles
                WHERE status = 'processed'
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [queries.row_to_dict(r) for r in cur.fetchall()]


@router.post("/ingest/rss")
def ingest_all_rss(background_tasks: BackgroundTasks):
    """Trigger a full RSS refresh across all sections (runs in background)."""
    background_tasks.add_task(_run_full_rss_ingest)
    return {"ok": True, "feeds": len(__import__("app.ingest.rss_ingest", fromlist=["ALL_FEEDS"]).ALL_FEEDS), "status": "fetching"}


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


def _fetch_section(prompt: str) -> None:
    """Background/startup article generation — skips Gemini to preserve quota."""
    try:
        write_article_from_prompt(prompt, limit=15, use_gemini=False)
    except Exception:
        logger.exception("Background section article generation failed", extra={"prompt": prompt})


def _run_full_rss_ingest() -> None:
    try:
        from app.main import _ingest_and_enrich
        articles = fetch_all_rss_fast(max_per_section=12)
        _ingest_and_enrich(articles)
    except Exception:
        logger.exception("Full RSS ingest task failed")


def _run_section_rss_ingest(section: str, enrich: bool) -> None:
    try:
        from app.main import _ingest_and_enrich
        articles = fetch_section_rss(section, enrich=enrich, max_articles=40)
        _ingest_and_enrich(articles)
    except Exception:
        logger.exception("Section RSS ingest task failed", extra={"section": section, "enrich": enrich})
