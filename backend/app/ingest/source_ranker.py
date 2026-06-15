from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlparse

from app.ingest.source_registry import DEFAULT_SOURCES, domain_from_url, is_blocked_domain


STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "is", "was",
    "at", "to", "from", "with", "by", "that", "this", "it", "its", "be",
    "are", "were", "has", "have", "had", "as", "new", "will", "more",
    "said", "says", "about", "after", "over", "into", "also", "than",
    "latest", "breaking", "current", "today", "update", "updates",
})

CURRENT_NEWS_MARKERS = frozenset({
    "latest", "breaking", "current", "today", "tonight", "now", "live",
    "recent", "new", "update", "updates", "this morning", "this week",
})

AGGREGATOR_DOMAINS = frozenset({
    "news.google.com", "google.com", "bing.com", "msn.com", "news.yahoo.com",
    "apple.news", "flipboard.com", "ground.news", "smartnews.com",
})

LOW_QUALITY_DOMAINS = frozenset({
    "medium.com", "substack.com", "wordpress.com", "blogspot.com",
    "prnewswire.com", "globenewswire.com", "businesswire.com",
})

_SOURCE_TIERS: dict[str, str] = {
    source["domain"]: source.get("reliability_tier", "standard")
    for source in DEFAULT_SOURCES
}
_TIER_SCORE = {
    "high": 1.0,
    "standard": 0.78,
    "opinion-heavy": 0.46,
}


@dataclass(frozen=True)
class SourceGate:
    min_sources: int = 4
    min_domains: int = 3
    min_text_chars: int = 300
    max_current_age_days: int = 14


def prompt_implies_current_news(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(marker in lowered for marker in CURRENT_NEWS_MARKERS)


def parse_article_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                compact = re.sub(r"\D", "", raw)
                if len(compact) >= 14:
                    try:
                        dt = datetime.strptime(compact[:14], "%Y%m%d%H%M%S")
                    except ValueError:
                        return None
                else:
                    return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def article_domain(article: dict) -> str:
    return (article.get("domain") or domain_from_url(article.get("url", ""))).lower()


def _domain_matches(domain: str, candidate: str) -> bool:
    return domain == candidate or domain.endswith("." + candidate)


def is_aggregator_url(url: str) -> bool:
    domain = domain_from_url(url)
    return any(_domain_matches(domain, blocked) for blocked in AGGREGATOR_DOMAINS)


def is_low_quality_domain(url: str) -> bool:
    domain = domain_from_url(url)
    return any(_domain_matches(domain, low) for low in LOW_QUALITY_DOMAINS)


def _prompt_keywords(prompt: str) -> frozenset[str]:
    return frozenset(
        word for word in re.findall(r"[a-z0-9]{3,}", prompt.lower())
        if word not in STOPWORDS
    )


def _article_keywords(article: dict) -> frozenset[str]:
    text = " ".join([
        str(article.get("title", "")),
        str(article.get("description", "")),
        str(article.get("raw_text", ""))[:2500],
        str(article.get("clean_text", ""))[:2500],
    ]).lower()
    return frozenset(re.findall(r"[a-z0-9]{3,}", text)) - STOPWORDS


def relevance_score(article: dict, prompt: str) -> float:
    keywords = _prompt_keywords(prompt)
    if not keywords:
        return 1.0
    title = str(article.get("title", "")).lower()
    body = " ".join([
        str(article.get("description", "")),
        str(article.get("raw_text", ""))[:2500],
        str(article.get("clean_text", ""))[:2500],
    ]).lower()
    article_words = _article_keywords(article)
    overlap = len(keywords & article_words) / len(keywords)
    title_words = frozenset(re.findall(r"[a-z0-9]{3,}", title)) - STOPWORDS
    title_overlap = len(keywords & title_words) / len(keywords)
    phrase_bonus = 0.18 if prompt.lower().strip() and prompt.lower().strip() in f"{title} {body}" else 0.0
    return min(1.0, overlap * 0.68 + title_overlap * 0.28 + phrase_bonus)


def _reliability_score(article: dict) -> float:
    explicit = str(article.get("reliability_tier", "")).lower()
    if explicit:
        return _TIER_SCORE.get(explicit, 0.62)
    domain = article_domain(article)
    for known, tier in _SOURCE_TIERS.items():
        if _domain_matches(domain, known):
            return _TIER_SCORE.get(tier, 0.62)
    return 0.62


def _recency_score(article: dict, *, now: datetime | None = None) -> float:
    dt = parse_article_datetime(article.get("published_at"))
    if not dt:
        return 0.45
    now = now or datetime.now(timezone.utc)
    age_days = max(0.0, (now - dt).total_seconds() / 86400)
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.88
    if age_days <= 14:
        return 0.72
    if age_days <= 30:
        return 0.45
    return 0.12


def _length_score(article: dict) -> float:
    text_len = max(
        len(str(article.get("clean_text", ""))),
        len(str(article.get("raw_text", ""))),
        len(str(article.get("description", ""))),
    )
    if text_len >= 2500:
        return 1.0
    if text_len >= 1200:
        return 0.86
    if text_len >= 500:
        return 0.68
    if text_len >= 160:
        return 0.42
    return 0.15


def _syndication_penalty(article: dict, seen_titles: dict[str, int]) -> float:
    title = re.sub(r"\W+", " ", str(article.get("title", "")).lower()).strip()
    if not title:
        return 0.0
    key = " ".join(w for w in title.split() if w not in STOPWORDS)[:90]
    seen_titles[key] = seen_titles.get(key, 0) + 1
    if seen_titles[key] == 1:
        return 0.0
    return min(0.22, 0.08 * (seen_titles[key] - 1))


def source_score(
    article: dict,
    prompt: str,
    *,
    seen_domains: set[str] | None = None,
    seen_titles: dict[str, int] | None = None,
    now: datetime | None = None,
) -> float:
    domain = article_domain(article)
    if not article.get("url") or is_blocked_domain(str(article.get("url", ""))):
        return -1.0

    score = (
        _reliability_score(article) * 0.24
        + _recency_score(article, now=now) * 0.20
        + _length_score(article) * 0.20
        + relevance_score(article, prompt) * 0.26
    )
    if seen_domains is not None and domain not in seen_domains:
        score += 0.08
    if is_aggregator_url(str(article.get("url", ""))):
        score -= 0.35
    if is_low_quality_domain(str(article.get("url", ""))):
        score -= 0.20
    if seen_titles is not None:
        score -= _syndication_penalty(article, seen_titles)
    return round(score, 4)


def _unwrap_redirect_candidate(article: dict) -> dict:
    url = str(article.get("url", ""))
    parsed = urlparse(url)
    if not is_aggregator_url(url):
        return article
    params = parse_qs(parsed.query)
    for key in ("url", "u", "q"):
        target = params.get(key, [""])[0]
        if target.startswith("http"):
            return {**article, "url": target, "domain": domain_from_url(target)}
    return article


def rank_sources(
    articles: list[dict],
    prompt: str,
    *,
    limit: int | None = None,
    require_current: bool | None = None,
    min_relevance: float = 0.18,
    min_text_chars: int = 80,
    allow_fallback: bool = True,
    now: datetime | None = None,
) -> tuple[list[dict], dict]:
    require_current = prompt_implies_current_news(prompt) if require_current is None else require_current
    now = now or datetime.now(timezone.utc)
    rejected: dict[str, int] = {}
    accepted: list[dict] = []
    seen_urls: set[str] = set()

    def reject(reason: str) -> None:
        rejected[reason] = rejected.get(reason, 0) + 1

    for original in articles:
        article = _unwrap_redirect_candidate(original)
        url = str(article.get("url", ""))
        if not url or url in seen_urls:
            reject("duplicate_url")
            continue
        seen_urls.add(url)
        if is_blocked_domain(url):
            reject("blocked_domain")
            continue
        if is_aggregator_url(url):
            reject("aggregator_url")
            continue
        text_len = max(len(str(article.get("clean_text", ""))), len(str(article.get("raw_text", ""))))
        if text_len < min_text_chars:
            reject("insufficient_text")
            continue
        rel = relevance_score(article, prompt)
        if rel < min_relevance:
            reject("low_relevance")
            continue
        if require_current:
            dt = parse_article_datetime(article.get("published_at"))
            if dt and (now - dt).days > 14:
                reject("stale_for_current_prompt")
                continue
        accepted.append({**article, "domain": article_domain(article), "relevance_score": round(rel, 3)})

    fallback_used = False
    if allow_fallback and len(accepted) < 3:
        fallback_used = True
        accepted = []
        for original in articles:
            article = _unwrap_redirect_candidate(original)
            url = str(article.get("url", ""))
            if not url or is_blocked_domain(url) or url in {a.get("url") for a in accepted}:
                continue
            if is_aggregator_url(url):
                continue
            text_len = max(len(str(article.get("clean_text", ""))), len(str(article.get("raw_text", ""))))
            if text_len < min_text_chars:
                continue
            if require_current:
                dt = parse_article_datetime(article.get("published_at"))
                if dt and (now - dt).days > 14:
                    continue
            if relevance_score(article, prompt) < min(0.10, min_relevance):
                continue
            accepted.append({**article, "domain": article_domain(article), "relevance_score": round(relevance_score(article, prompt), 3)})

    seen_domains: set[str] = set()
    seen_titles: dict[str, int] = {}
    scored: list[dict] = []
    for article in accepted:
        score = source_score(article, prompt, seen_domains=seen_domains, seen_titles=seen_titles, now=now)
        seen_domains.add(article_domain(article))
        scored.append({**article, "source_score": score})

    scored.sort(key=lambda item: item.get("source_score", 0), reverse=True)
    if limit is not None:
        diversified: list[dict] = []
        deferred: list[dict] = []
        selected_domains: set[str] = set()
        for item in scored:
            domain = article_domain(item)
            if domain and domain not in selected_domains:
                diversified.append(item)
                selected_domains.add(domain)
            else:
                deferred.append(item)
            if len(diversified) >= limit:
                break
        scored = (diversified + deferred)[:limit]

    domains = {article_domain(a) for a in scored if article_domain(a)}
    usable = [a for a in scored if max(len(str(a.get("clean_text", ""))), len(str(a.get("raw_text", "")))) >= min_text_chars]
    meta = {
        "candidate_count": len(articles),
        "ranked_count": len(scored),
        "usable_source_count": len(usable),
        "domain_count": len(domains),
        "domains": sorted(domains),
        "fallback_used": fallback_used,
        "rejected": rejected,
        "average_source_score": round(sum(a.get("source_score", 0) for a in scored) / len(scored), 3) if scored else 0,
    }
    return scored, meta


def evaluate_source_quality(
    articles: list[dict],
    prompt: str,
    *,
    gate: SourceGate = SourceGate(),
    require_current: bool | None = None,
    now: datetime | None = None,
) -> dict:
    require_current = prompt_implies_current_news(prompt) if require_current is None else require_current
    now = now or datetime.now(timezone.utc)
    usable = [
        a for a in articles
        if max(len(str(a.get("clean_text", ""))), len(str(a.get("raw_text", "")))) >= gate.min_text_chars
    ]
    domains = {article_domain(a) for a in usable if article_domain(a)}
    stale = 0
    if require_current:
        for article in usable:
            dt = parse_article_datetime(article.get("published_at"))
            if dt and (now - dt).days > gate.max_current_age_days:
                stale += 1

    failed = []
    if len(usable) < gate.min_sources:
        failed.append("minimum_usable_source_count")
    if len(domains) < gate.min_domains:
        failed.append("minimum_domain_diversity")
    if require_current and stale:
        failed.append("source_recency")

    if not articles:
        level = "none"
    elif failed:
        level = "limited"
    elif len(usable) >= 6 and len(domains) >= 4:
        level = "strong"
    else:
        level = "adequate"

    return {
        "level": level,
        "usable_source_count": len(usable),
        "domain_count": len(domains),
        "minimum_usable_source_count": gate.min_sources,
        "minimum_domain_diversity": gate.min_domains,
        "minimum_text_length": gate.min_text_chars,
        "current_news_required": require_current,
        "stale_source_count": stale,
        "failed_gates": failed,
    }
