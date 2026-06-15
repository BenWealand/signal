from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from app.ingest.source_registry import domain_from_url, guess_source_from_url


# Words too generic to be useful for relevance scoring
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "is", "was",
    "at", "to", "from", "with", "by", "that", "this", "it", "its", "be",
    "are", "were", "has", "have", "had", "as", "new", "will", "more",
    "said", "says", "about", "after", "over", "into", "also", "than",
})


def _prompt_to_gdelt_query(prompt: str) -> str:
    """
    Convert a plain-text prompt into a GDELT Doc API query string.
    - Multi-word phrases get quoted so GDELT treats them as a unit.
    - Single-word terms are kept as-is.
    - `sourcelang:english` is appended so only English articles come back.
    """
    prompt = prompt.strip()
    # Quote multi-word prompts so GDELT treats the whole phrase as a near-match
    words = prompt.split()
    if len(words) >= 2:
        # Quote first-pass as a phrase, then add individual meaningful words
        meaningful = [w for w in words if w.lower() not in _STOPWORDS and len(w) >= 3]
        if len(meaningful) >= 2:
            query = f'"{" ".join(meaningful[:4])}"'
        else:
            query = prompt
    else:
        query = prompt
    return f"{query} sourcelang:english"


def _relevance_score(article: dict, prompt_words: frozenset[str]) -> float:
    """
    Fraction of prompt keywords found in the article title + snippet.
    Returns 0.0–1.0. Articles with 0 overlap are completely irrelevant.
    """
    if not prompt_words:
        return 1.0
    text = (
        (article.get("title", "") + " " + article.get("raw_text", "")).lower()
    )
    text_words = frozenset(re.findall(r"[a-z]{3,}", text))
    overlap = prompt_words & text_words
    return len(overlap) / len(prompt_words)


def fetch_gdelt_articles(
    query: str,
    limit: int = 15,
    min_relevance: float = 0.20,
) -> list[dict[str, str]]:
    """
    Fetch articles from GDELT Doc API v2.

    Parameters
    ----------
    query:
        Plain-text search prompt. Gets converted to a GDELT query string.
    limit:
        Max records to request from GDELT. We over-fetch (up to 2×) so
        relevance filtering still leaves enough articles.
    min_relevance:
        Minimum keyword-overlap fraction between the article and the prompt.
        Articles below this threshold are dropped. Set to 0 to keep all.
    """
    gdelt_query = _prompt_to_gdelt_query(query)
    fetch_limit = min(limit * 2, 250)

    params = urllib.parse.urlencode({
        "query": gdelt_query,
        "mode": "ArtList",
        "format": "json",
        "maxrecords": fetch_limit,
        "sort": "HybridRel",
        "timespan": "2W",   # last 2 weeks — keeps results fresh and relevant
    })
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?{params}"

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []

    # Keywords we'll use to score each article's relevance to the prompt
    prompt_words = frozenset(
        w for w in re.findall(r"[a-z]{3,}", query.lower())
        if w not in _STOPWORDS
    )

    articles = []
    for item in payload.get("articles", []):
        article_url = item.get("url", "")
        source_name = item.get("sourceCommonName") or guess_source_from_url(article_url)
        title = item.get("title", "").strip() or "Untitled"
        snippet = (item.get("snippet", "") or "").strip()
        raw_text = f"{title}. {snippet}".strip()

        candidate = {
            "source_name": source_name,
            "domain": domain_from_url(article_url),
            "title": title,
            "url": article_url,
            "published_at": item.get("seendate", ""),
            "description": title,
            "raw_text": raw_text,
            "topic": query,
            "language": "en",
            "status": "new",
        }

        score = _relevance_score(candidate, prompt_words)
        if score >= min_relevance:
            articles.append(candidate)
            if len(articles) >= limit:
                break

    return articles
