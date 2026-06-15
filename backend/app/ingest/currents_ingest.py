from __future__ import annotations

import json
import urllib.parse
import urllib.request

from app.config import settings
from app.ingest.source_registry import domain_from_url, is_blocked_domain

_API_BASE = "https://api.currentsapi.services/v1/search"

_MAX_PER_QUERY = 8


def fetch_currents_articles(query: str, max_results: int = _MAX_PER_QUERY) -> list[dict]:
    """
    Fetch articles from Currents API (free tier: 600 req/day).
    Returns title + description for up to max_results articles.
    One HTTP request per call — quota-safe.
    """
    key = settings.currents_api_key
    if not key:
        return []

    params = urllib.parse.urlencode({
        "keywords": query,
        "language": "en",
        "apiKey": key,
        "limit": min(max_results, _MAX_PER_QUERY),
    })
    url = f"{_API_BASE}?{params}"

    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SignalNewsBot/1.0 (news transparency research)"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        articles: list[dict] = []
        for item in data.get("news", []):
            article_url = (item.get("url") or "").strip()
            if not article_url or is_blocked_domain(article_url):
                continue

            title       = (item.get("title")       or "").strip()
            description = (item.get("description") or "").strip()
            raw_text    = f"{title}. {description}".strip() if description else title

            domain = domain_from_url(article_url)
            source_name = domain.replace("www.", "").split(".")[0].title() or "Currents"

            articles.append({
                "source_name": source_name,
                "domain":      domain,
                "title":       title,
                "url":         article_url,
                "published_at": item.get("published", ""),
                "description": description[:500],
                "raw_text":    raw_text,
                "topic":       query,
                "rss_url":     "",
                "language":    "en",
                "status":      "new",
            })
        return articles

    except Exception:
        return []
