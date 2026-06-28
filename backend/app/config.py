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
    claim_model: str = os.getenv("CLAIM_MODEL", "gpt-4o-mini")
    summary_model: str = os.getenv("SUMMARY_MODEL", "gpt-4o-mini")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    use_llm_claims: bool = os.getenv("USE_LLM_CLAIMS", "false").lower() == "true"
    auto_ingest_on_startup: bool = os.getenv("SIGNAL_AUTO_INGEST_ON_STARTUP", "true").lower() == "true"
    periodic_rss: bool = os.getenv("SIGNAL_PERIODIC_RSS", "true").lower() == "true"
    app_name: str = "Signal News Intelligence API"


settings = Settings()
