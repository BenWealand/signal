from __future__ import annotations

import json
import urllib.parse
import urllib.request

from app.config import settings
from app.ingest.source_registry import domain_from_url, is_blocked_domain

_API_BASE = "https://gnews.io/api/v4/search"

_MAX_PER_QUERY = 8


def fetch_gnews_articles(query: str, max_results: int = _MAX_PER_QUERY) -> list[dict]:
    """
    Fetch articles from GNews API (free tier: 100 req/day).
    Returns title + description + truncated content for up to max_results articles.
    One HTTP request per call — quota-safe.
    """
    key = settings.gnews_api_key
    if not key:
        return []

    params = urllib.parse.urlencode({
        "q":      query,
        "lang":   "en",
        "max":    min(max_results, _MAX_PER_QUERY),
        "apikey": key,
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
        for item in data.get("articles", []):
            article_url = (item.get("url") or "").strip()
            if not article_url or is_blocked_domain(article_url):
                continue

            source_name = (item.get("source", {}).get("name") or "").strip()
            if not source_name:
                source_name = domain_from_url(article_url).replace("www.", "").split(".")[0].title()

            title       = (item.get("title")       or "").strip()
            description = (item.get("description") or "").strip()
            content     = (item.get("content")     or "").strip()

            # GNews free tier truncates content to ~300 chars; description is usually fuller
            best_text = content if len(content) > len(description) else description
            raw_text  = f"{title}. {best_text}".strip() if best_text else title

            articles.append({
                "source_name": source_name,
                "domain":      domain_from_url(article_url),
                "title":       title,
                "url":         article_url,
                "published_at": item.get("publishedAt", ""),
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
