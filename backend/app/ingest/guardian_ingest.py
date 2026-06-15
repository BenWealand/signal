from __future__ import annotations

import json
import urllib.parse
import urllib.request

from app.config import settings

_API_BASE = "https://content.guardianapis.com/search"


def fetch_guardian_articles(query: str, max_articles: int = 5) -> list[dict]:
    """
    max_articles capped at 5 per query to stay well within the 500 req/day
    free tier (each article = 1 API call internally; page fetch = 1 request).
    """
    """
    Fetch full-text articles from The Guardian's free Open API.

    Returns articles with complete body text — no scraping required.
    Coverage: world news, politics, business, technology, science, sport,
              environment, culture, and more.
    """
    api_key = settings.guardian_content_api_key
    encoded = urllib.parse.quote_plus(query)
    url = (
        f"{_API_BASE}"
        f"?q={encoded}"
        f"&api-key={api_key}"
        f"&show-fields=bodyText,trailText,headline,byline"
        f"&order-by=relevance"
        f"&page-size={min(max_articles, 10)}"
    )
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SignalNewsBot/1.0 (news transparency research)"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        results = data.get("response", {}).get("results", [])
        articles: list[dict] = []

        for item in results:
            fields = item.get("fields", {})
            body  = (fields.get("bodyText")  or "").strip()
            trail = (fields.get("trailText") or "").strip()
            headline = (fields.get("headline") or item.get("webTitle") or "").strip()
            article_url  = item.get("webUrl", "")
            pub_date     = item.get("webPublicationDate", "")
            section      = item.get("sectionName", "")

            # Use full body when available, fall back to trail text
            content = body if len(body) > len(trail) else trail
            if not content:
                continue

            articles.append({
                "source_name": "The Guardian",
                "domain": "theguardian.com",
                "title": headline,
                "url": article_url,
                "published_at": pub_date,
                "description": trail[:500],
                "raw_text": f"{headline}. {content}",
                "topic": section.lower(),
                "rss_url": "",
                "language": "en",
                "status": "new",
            })

        return articles

    except Exception:
        return []
