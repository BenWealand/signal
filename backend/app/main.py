from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_articles import router as article_router
from app.api.routes_news import router as news_router
from app.api.routes_news import SECTION_PROMPTS, _fetch_section
from app.api.routes_search import router as search_router
from app.api.routes_stories import router as story_router
from app.api.routes_users import router as user_router
from app.config import settings
from app.db.connection import create_tables, get_connection
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

app.include_router(story_router)
app.include_router(article_router)
app.include_router(search_router)
app.include_router(user_router)
app.include_router(news_router)

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
    then regenerate one synthesised article per section so Trends stays current.
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
            for prompt in SECTION_PROMPTS.values():
                _fetch_section(prompt)
        except Exception:
            log_event(logger, "periodic_section_synthesis_failed", level=logging.ERROR)
            logger.exception("Periodic section synthesis failed")


def _startup_pipeline() -> None:
    """
    Background thread: fast RSS fetch → insert snippets → enrich full text
    → synthesise one generated article per section (so Trends is populated).
    """
    try:
        # Phase 1: fetch all RSS feeds (fast — title + description only)
        articles = fetch_all_rss_fast(max_per_section=10)
        _ingest_and_enrich(articles)
    except Exception:
        log_event(logger, "startup_rss_ingest_failed", level=logging.ERROR)
        logger.exception("Startup RSS ingest failed")

    try:
        # Phase 2: run write_article_from_prompt for every section.
        # This combines the freshly ingested RSS articles with GDELT results
        # and saves them to generated_articles, so they appear in Trends + Latest.
        for prompt in SECTION_PROMPTS.values():
            _fetch_section(prompt)
    except Exception:
        log_event(logger, "startup_section_synthesis_failed", level=logging.ERROR)
        logger.exception("Startup section synthesis failed")


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


@app.get("/health")
def health():
    database = dict(_database_status)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        database = {"ok": True, "type": "postgres", "error": ""}
    except Exception as exc:
        database = {"ok": False, "type": "postgres", "error": str(exc)}

    from app.ingest.rss_ingest import ALL_FEEDS

    return {
        "ok": bool(database.get("ok")),
        "database": database,
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
