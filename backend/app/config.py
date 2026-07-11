from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[1]

try:
    from dotenv import load_dotenv

    load_dotenv(BACKEND_ROOT / ".env")
except Exception:
    logger.exception("Failed to load backend .env file")


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    supabase_jwt_secret: str = os.getenv("SUPABASE_JWT_SECRET", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    news_api_key: str = os.getenv("NEWS_API_KEY", "")
    currents_api_key: str = os.getenv("CURRENTS_API_KEY", "")
    gnews_api_key: str = os.getenv("GNEWS_API_KEY", "")
    guardian_content_api_key: str = os.getenv("GUARDIAN_CONTENT_API_KEY", "")
    google_fact_check_api_key: str = os.getenv("GOOGLE_FACT_CHECK_API_KEY", "")
    signal_api_token: str = os.getenv("SIGNAL_API_TOKEN", "")
    public_article_base_url: str = os.getenv("PUBLIC_ARTICLE_BASE_URL", "")
    rss_feeds: str = os.getenv("RSS_FEEDS", "")
    gdelt_queries: str = os.getenv("GDELT_QUERIES", "")
    cors_origins: str = os.getenv("CORS_ORIGINS", "")
    cors_origin_regex: str = os.getenv("CORS_ORIGIN_REGEX", "")
    prompt_blacklist: str = os.getenv("PROMPT_BLACKLIST", "")
    prompt_blacklist_regex: str = os.getenv("PROMPT_BLACKLIST_REGEX", "")
    claim_model: str = os.getenv("CLAIM_MODEL", "gpt-4o-mini")
    summary_model: str = os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
    # "gemini-flash-latest" is a Google-maintained alias that always points at
    # the current flash model, so writes keep working when pinned model ids
    # (like the retired gemini-2.0-flash) are shut down.
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    use_llm_claims: bool = os.getenv("USE_LLM_CLAIMS", "false").lower() == "true"
    auto_ingest_on_startup: bool = os.getenv("SIGNAL_AUTO_INGEST_ON_STARTUP", "false").lower() == "true"
    periodic_rss: bool = os.getenv("SIGNAL_PERIODIC_RSS", "false").lower() == "true"
    embedding_warmup_on_startup: bool = os.getenv("SIGNAL_EMBEDDING_WARMUP_ON_STARTUP", "false").lower() == "true"
    db_pool_max: int = int(os.getenv("DB_POOL_MAX", "8"))
    feed_cache_ttl_seconds: int = int(os.getenv("FEED_CACHE_TTL_SECONDS", "30"))
    section_fast_articles_per_refresh: int = int(os.getenv("SIGNAL_SECTION_FAST_COUNT", "3"))
    section_fast_min_age_minutes: int = int(os.getenv("SIGNAL_SECTION_FAST_MIN_AGE_MINUTES", "45"))
    # Daily source refresh keeps the article cache warm so Fast mode can
    # answer from Postgres before hitting live providers.
    daily_ingest_enabled: bool = os.getenv("SIGNAL_DAILY_INGEST", "false").lower() == "true"
    daily_ingest_interval_seconds: int = int(os.getenv("SIGNAL_DAILY_INGEST_INTERVAL_SECONDS", "86400"))
    # Fast writes use the lite model; thorough keeps the primary flash model
    # but with tighter enrich caps so it still returns quickly.
    gemini_fast_model: str = os.getenv("GEMINI_FAST_MODEL", "gemini-flash-lite-latest")
    fast_cache_min_sources: int = int(os.getenv("SIGNAL_FAST_CACHE_MIN_SOURCES", "4"))
    thorough_cache_min_sources: int = int(os.getenv("SIGNAL_THOROUGH_CACHE_MIN_SOURCES", "5"))
    thorough_enrich_limit: int = int(os.getenv("SIGNAL_THOROUGH_ENRICH_LIMIT", "6"))
    thorough_enrich_timeout_seconds: int = int(os.getenv("SIGNAL_THOROUGH_ENRICH_TIMEOUT", "5"))
    thorough_max_candidates: int = int(os.getenv("SIGNAL_THOROUGH_MAX_CANDIDATES", "10"))
    # X / Twitter workflow — credentials are optional until you implement app/x/client.py
    x_api_bearer_token: str = os.getenv("X_API_BEARER_TOKEN", "")
    x_api_key: str = os.getenv("X_API_KEY", "")
    x_api_secret: str = os.getenv("X_API_SECRET", "")
    x_access_token: str = os.getenv("X_ACCESS_TOKEN", "")
    x_access_token_secret: str = os.getenv("X_ACCESS_TOKEN_SECRET", "")
    x_trends_woeid: int = int(os.getenv("X_TRENDS_WOEID", "1"))
    # Keep dry-run on until post_tweet() is implemented and verified.
    x_dry_run: bool = os.getenv("SIGNAL_X_DRY_RUN", "true").lower() != "false"
    x_auto_post: bool = os.getenv("SIGNAL_X_AUTO_POST", "false").lower() == "true"
    # Comma-separated admin emails (lowercase). Default: sole admin.
    admin_emails: str = os.getenv("SIGNAL_ADMIN_EMAILS", "benwealand@gmail.com")
    app_name: str = "Signal News Intelligence API"


settings = Settings()


def admin_email_set() -> set[str]:
    return {
        email.strip().lower()
        for email in (settings.admin_emails or "").split(",")
        if email.strip()
    }
