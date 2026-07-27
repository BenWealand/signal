from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.api.middleware import FeedCacheHeadersMiddleware, SecurityHeadersMiddleware
from app.api.routes_articles import router as article_router
from app.api.routes_x import router as x_router
from app.api.routes_feeds import router as feeds_router
from app.api.routes_news import router as news_router
from app.api.routes_news import SECTION_SLUGS, _generate_fast_section_articles
from app.api.routes_search import router as search_router
from app.api.routes_stories import router as story_router
from app.api.routes_users import router as user_router
from app.api.routes_admin import router as admin_router
from app.api.routes_vm import router as vm_router
from app.config import settings
from app.db.connection import create_tables, get_connection, close_pool
from app.db import queries
from app.ingest.rss_ingest import fetch_all_rss_fast, enrich_articles_in_background
from app.observability import log_event

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)

DEFAULT_CORS_ORIGINS = [
    "http://127.0.0.1:5175",
    "http://localhost:5175",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
]


def _cors_origins() -> list[str]:
    configured = [origin.strip().rstrip("/") for origin in settings.cors_origins.split(",") if origin.strip()]
    return [*DEFAULT_CORS_ORIGINS, *configured]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(FeedCacheHeadersMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(story_router)
app.include_router(article_router)
app.include_router(x_router)
app.include_router(feeds_router)
app.include_router(search_router)
app.include_router(user_router)
app.include_router(admin_router)
app.include_router(news_router)
app.include_router(vm_router)

_database_status: dict[str, str | bool] = {
    "ok": False,
    "type": "postgres",
    "error": "Startup has not checked the database yet.",
}


def _ingest_and_enrich(articles: list[dict]) -> None:
    """Insert articles (snippets) immediately, then enrich each with full text."""
    inserted: list[dict] = []
    for article in articles:
        try:
            aid = queries.insert_article(article)
            inserted.append({**article, "id": aid})
        except Exception:
            log_event(logger, "rss_insert_failed", level=logging.ERROR, url=article.get("url"), title=article.get("title"))
            logger.exception("Failed to insert RSS article during background ingest")
    # Full-text enrichment pass — updates raw_text in DB for each article
    enriched = enrich_articles_in_background(inserted, workers=10)
    for article in enriched:
        try:
            if article.get("id") and article.get("raw_text"):
                from app.processing.clean_text import clean_article_text
                from app.nlp.ner import extract_entities
                from app.llm.claim_extractor import extract_claims
                clean_text = clean_article_text(str(article["raw_text"]))
                entities = extract_entities(clean_text)
                entity_names = [str(e["text"]) for e in entities]
                claims = extract_claims(clean_text, entities=entity_names)
                queries.update_article_processing(int(article["id"]), clean_text, "processed")
                queries.replace_entities(int(article["id"]), entities)
                queries.replace_claims(int(article["id"]), claims)
        except Exception:
            log_event(logger, "rss_enrich_process_failed", level=logging.ERROR, article_id=article.get("id"), url=article.get("url"))
            logger.exception("Failed to enrich/process article during background ingest")


def _periodic_rss_refresh(interval_seconds: int = 900) -> None:
    """
    Daemon thread: re-fetch RSS feeds every `interval_seconds` (default 15 min),
    then generate shared fast-mode articles per section so feeds stay current.
    """
    while True:
        time.sleep(interval_seconds)
        try:
            articles = fetch_all_rss_fast(max_per_section=10)
            _ingest_and_enrich(articles)
        except Exception:
            log_event(logger, "periodic_rss_refresh_failed", level=logging.ERROR)
            logger.exception("Periodic RSS refresh failed")
        try:
            for section in SECTION_SLUGS:
                _generate_fast_section_articles(section)
        except Exception:
            log_event(logger, "periodic_section_synthesis_failed", level=logging.ERROR)
            logger.exception("Periodic section fast generation failed")


def run_daily_source_refresh(*, synthesize_sections: bool = True) -> dict:
    """
    Pull a fresh day of RSS coverage into Postgres so Fast mode can draft
    from cache before hitting live providers.
    """
    started = time.monotonic()
    articles = fetch_all_rss_fast(max_per_section=14)
    _ingest_and_enrich(articles)
    section_count = 0
    if synthesize_sections:
        for section in SECTION_SLUGS:
            try:
                _generate_fast_section_articles(section)
                section_count += 1
            except Exception:
                log_event(logger, "daily_section_synthesis_failed", level=logging.ERROR, section=section)
                logger.exception("Daily section fast generation failed", extra={"section": section})
    return {
        "ok": True,
        "ingested": len(articles),
        "sections": section_count,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }


def _daily_ingest_loop(interval_seconds: int = 86400) -> None:
    """Daemon: refresh the desk cache about once per day."""
    # Run soon after boot so the first Fast drafts can use warm coverage,
    # then settle into the daily cadence.
    time.sleep(20)
    while True:
        try:
            result = run_daily_source_refresh(synthesize_sections=True)
            log_event(logger, "daily_source_refresh_complete", **result)
        except Exception:
            log_event(logger, "daily_source_refresh_failed", level=logging.ERROR)
            logger.exception("Daily source refresh failed")
        time.sleep(max(3600, interval_seconds))


def _startup_pipeline() -> None:
    """
    Background thread: fast RSS fetch → insert snippets → enrich full text
    → generate shared fast-mode articles per section (so feeds are populated).
    """
    try:
        # Phase 1: fetch all RSS feeds (fast — title + description only)
        articles = fetch_all_rss_fast(max_per_section=10)
        _ingest_and_enrich(articles)
    except Exception:
        log_event(logger, "startup_rss_ingest_failed", level=logging.ERROR)
        logger.exception("Startup RSS ingest failed")

    try:
        # Phase 2: save several fast-mode section articles to generated_articles
        # so every reader sees the same shared feed items.
        for section in SECTION_SLUGS:
            _generate_fast_section_articles(section)
    except Exception:
        log_event(logger, "startup_section_synthesis_failed", level=logging.ERROR)
        logger.exception("Startup section fast generation failed")


@app.on_event("startup")
def startup() -> None:
    global _database_status
    try:
        create_tables()
        purge_result = queries.purge_blacklisted_generated_articles()
        if purge_result.get("deleted"):
            logger.info("Purged blacklisted generated articles on startup", extra=purge_result)
        _database_status = {"ok": True, "type": "postgres", "error": ""}
    except Exception as exc:
        _database_status = {"ok": False, "type": "postgres", "error": str(exc)}
    if settings.embedding_warmup_on_startup:
        try:
            from app.llm.embeddings import warmup as _embed_warmup
            _embed_warmup()
        except Exception:
            logger.exception("Embedding warmup failed")
    if settings.auto_ingest_on_startup:
        threading.Thread(target=_startup_pipeline, daemon=True).start()
    if settings.periodic_rss:
        threading.Thread(target=_periodic_rss_refresh, args=(900,), daemon=True).start()
    if settings.daily_ingest_enabled and not settings.periodic_rss and not settings.auto_ingest_on_startup:
        # When the heavier periodic ingest is off (typical free-tier), still
        # refresh the source desk about once per day for cache-first Fast writes.
        threading.Thread(
            target=_daily_ingest_loop,
            args=(settings.daily_ingest_interval_seconds,),
            daemon=True,
            name="daily-source-refresh",
        ).start()


@app.on_event("shutdown")
def shutdown() -> None:
    close_pool()


@app.get("/health")
def health():
    database = dict(_database_status)
    auth_schema = {"users_role": False, "migrations": []}
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'role'
                    """
                )
                auth_schema["users_role"] = bool(cur.fetchone())
                try:
                    cur.execute("SELECT version FROM schema_migrations ORDER BY version")
                    auth_schema["migrations"] = [
                        (row["version"] if isinstance(row, dict) else row[0]) for row in cur.fetchall()
                    ]
                except Exception:
                    auth_schema["migrations"] = []
        database = {"ok": True, "type": "postgres", "error": ""}
    except Exception as exc:
        database = {"ok": False, "type": "postgres", "error": str(exc)}

    from app.ingest.rss_ingest import ALL_FEEDS

    return {
        "ok": bool(database.get("ok")),
        "database": database,
        "auth": {
            "jwt_secret_configured": bool((settings.supabase_jwt_secret or "").strip()),
            "supabase_url_configured": bool((settings.supabase_url or "").strip()),
            "schema": auth_schema,
        },
        "mode": "llm" if (settings.openai_api_key or settings.gemini_api_key) else "demo",
        "keys_configured": {
            "gemini": bool(settings.gemini_api_key),
            "openai": bool(settings.openai_api_key),
            "news_api": bool(settings.news_api_key),
            "currents": bool(settings.currents_api_key),
            "gnews": bool(settings.gnews_api_key),
            "guardian": bool(settings.guardian_content_api_key),
        },
        "rss_feed_count": len(ALL_FEEDS),
    }


@app.get("/awake")
def awake():
    return {"ok": True, "service": "signal-api"}
