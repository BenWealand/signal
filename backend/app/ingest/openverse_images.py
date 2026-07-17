from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from app.nlp.ner import extract_entities

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.openverse.org/v1/images/"
_ALLOWED_LICENSES = frozenset({"by", "by-sa", "cc0", "pdm"})
_ALLOWED_FILE_TYPES = frozenset({"jpg", "jpeg", "png", "webp"})
# Prefer visually concrete subjects first when choosing an Openverse query.
_IMAGE_ENTITY_PRIORITY = ("PERSON", "EVENT", "ORG", "GPE", "PRODUCT", "LAW", "DATE")
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "is", "was",
    "at", "to", "from", "with", "by", "that", "this", "it", "its", "be",
    "are", "were", "has", "have", "had", "as", "new", "will", "more",
    "said", "says", "about", "after", "over", "into", "also", "than",
    "latest", "update", "updates", "news", "review", "cross", "source",
    "what", "when", "where", "why", "how", "who", "happened", "happens",
})
_LOW_VALUE_IMAGE_TERMS = frozenset({
    "logo", "icon", "wordmark", "watermark", "placeholder", "avatar", "emoji",
})
_CACHE_TTL_SECONDS = 6 * 60 * 60
_cache_lock = threading.Lock()
_image_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _clean_text(value: Any, limit: int = 240) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _keywords(value: str) -> frozenset[str]:
    return frozenset(
        word
        for word in re.findall(r"[a-z0-9]{3,}", (value or "").lower())
        if word not in _STOPWORDS
    )


def _search_query(value: str) -> str:
    raw_words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", _clean_text(value, 300))
    start = next(
        (
            index
            for index, word in enumerate(raw_words)
            if len(word.strip("'-")) >= 3 and word.lower().strip("'-") not in _STOPWORDS
        ),
        None,
    )
    if start is None:
        return ""

    phrase: list[str] = []
    meaningful = 0
    for word in raw_words[start:]:
        normalized = word.lower().strip("'-")
        if not normalized:
            continue
        phrase.append(word)
        if len(normalized) >= 3 and normalized not in _STOPWORDS:
            meaningful += 1
        if meaningful >= 2:
            break
    subject = " ".join(phrase)
    return f'"{subject}"' if meaningful >= 2 else subject


def _format_entity_query(value: str) -> str:
    """Turn an NER span into a focused Openverse subject query."""
    cleaned = _clean_text(value, 120)
    if not cleaned:
        return ""
    meaningful: list[str] = []
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", cleaned):
        normalized = word.lower().strip("'-")
        if not normalized or normalized in _STOPWORDS:
            continue
        # Keep short numerals (dates, bill numbers) and normal words of length 3+.
        if normalized.isdigit() or len(normalized) >= 3:
            meaningful.append(word)
    if not meaningful:
        return ""
    subject = " ".join(meaningful[:4])
    return f'"{subject}"' if len(meaningful) >= 2 else subject


def priority_image_queries(text: str) -> list[str]:
    """Ordered Openverse subjects: people → event → org → place → product → law → date."""
    by_type: dict[str, list[str]] = {label: [] for label in _IMAGE_ENTITY_PRIORITY}
    for entity in extract_entities(text or ""):
        label = str(entity.get("type") or "").upper()
        if label not in by_type:
            continue
        query = _format_entity_query(str(entity.get("text") or ""))
        if query and query not in by_type[label]:
            by_type[label].append(query)

    subjects: list[str] = []
    for label in _IMAGE_ENTITY_PRIORITY:
        for query in by_type[label][:1]:
            if query not in subjects:
                subjects.append(query)

    fallback = _search_query(text or "")
    if fallback and fallback not in subjects:
        subjects.append(fallback)
    return subjects


def _valid_http_url(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return raw


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _tag_text(item: dict[str, Any]) -> str:
    tags = item.get("tags") or []
    values: list[str] = []
    for tag in tags[:20] if isinstance(tags, list) else []:
        values.append(str(tag.get("name") or "") if isinstance(tag, dict) else str(tag))
    return " ".join(values)


def _candidate_score(item: dict[str, Any], query_keywords: frozenset[str]) -> float:
    title = _clean_text(item.get("title"))
    candidate_keywords = _keywords(f"{title} {_tag_text(item)}")
    if not candidate_keywords or not query_keywords:
        return -1
    overlap = query_keywords & candidate_keywords
    if not overlap:
        return -1
    if _keywords(title) & _LOW_VALUE_IMAGE_TERMS:
        return -1

    width = _safe_int(item.get("width"))
    height = _safe_int(item.get("height"))
    if width and height:
        if width < 640 or height < 360:
            return -1
        ratio = width / height
        if ratio < 1.15 or ratio > 2.6:
            return -1

    title_overlap = len(query_keywords & _keywords(title))
    coverage = len(overlap) / max(1, len(query_keywords))
    return coverage * 10 + title_overlap * 2 + (1 if width >= 1200 else 0)


def _normalize_image(item: dict[str, Any], query: str) -> dict[str, Any]:
    license_code = str(item.get("license") or "").lower().strip()
    if license_code not in _ALLOWED_LICENSES:
        return {}
    file_type = str(item.get("filetype") or "").lower().lstrip(".")
    file_size = _safe_int(item.get("filesize"))
    if file_type and file_type not in _ALLOWED_FILE_TYPES:
        return {}
    if file_size > 12_000_000:
        return {}
    image_url = _valid_http_url(item.get("url")) or _valid_http_url(item.get("thumbnail"))
    source_url = _valid_http_url(item.get("foreign_landing_url")) or _valid_http_url(item.get("detail_url"))
    license_url = _valid_http_url(item.get("license_url"))
    if not image_url.startswith("https://") or not source_url or not license_url:
        return {}

    title = _clean_text(item.get("title")) or f"Image related to {query}"
    creator = _clean_text(item.get("creator"))
    if license_code in {"by", "by-sa"} and not creator:
        return {}
    creator = creator or "Public domain"
    return {
        "url": image_url,
        "alt": title,
        "title": title,
        "creator": creator,
        "creatorUrl": _valid_http_url(item.get("creator_url")),
        "license": license_code.upper(),
        "licenseUrl": license_url,
        "sourceUrl": source_url,
        "provider": "Openverse",
    }


def _lookup_openverse_image(clean_query: str, *, timeout: float) -> dict[str, Any]:
    """Return one ranked Openverse match for a prepared subject query, or {}."""
    query_keywords = _keywords(clean_query)
    if not clean_query or not query_keywords:
        return {}

    cache_key = clean_query.lower()
    now = time.monotonic()
    with _cache_lock:
        cached = _image_cache.get(cache_key)
        if cached and cached[0] > now:
            return dict(cached[1])

    params = urllib.parse.urlencode({
        "q": clean_query,
        "page_size": 12,
        "license": ",".join(sorted(_ALLOWED_LICENSES)),
        "mature": "false",
        "filter_dead": "true",
        "aspect_ratio": "wide",
    })
    request = urllib.request.Request(
        f"{_SEARCH_URL}?{params}",
        headers={
            "Accept": "application/json",
            "User-Agent": "SignalNewsBot/1.0 (open-media attribution lookup)",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
            payload = json.loads(response.read(1_500_000).decode("utf-8", errors="ignore"))
    except Exception as exc:
        logger.warning("Openverse image search failed", extra={"error_type": type(exc).__name__})
        return {}

    scored: list[tuple[float, dict[str, Any]]] = []
    results = (payload.get("results") or []) if isinstance(payload, dict) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_image(item, clean_query)
        if not normalized:
            continue
        score = _candidate_score(item, query_keywords)
        if score >= 0:
            scored.append((score, normalized))
    if not scored:
        return {}
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected = scored[0][1]
    with _cache_lock:
        if len(_image_cache) >= 128:
            _image_cache.pop(next(iter(_image_cache)))
        _image_cache[cache_key] = (now + _CACHE_TTL_SECONDS, selected)
    return dict(selected)


def find_openverse_image(query: str, *, timeout: float = 4.0) -> dict[str, Any]:
    """Return one relevant, attribution-ready open image or an empty dict.

    Search subjects prefer NER spans in this order: PERSON, EVENT, ORG, GPE,
    PRODUCT, LAW, DATE. Falls back to a prompt phrase when no entity matches.
    """
    subjects = priority_image_queries(query)
    if not subjects:
        return {}

    deadline = time.monotonic() + max(1.0, float(timeout))
    for index, subject in enumerate(subjects):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # Leave a little budget for later priority subjects when several remain.
        later = len(subjects) - index - 1
        per_try = remaining if later <= 0 else max(0.75, remaining / (later + 1))
        image = _lookup_openverse_image(subject, timeout=per_try)
        if image:
            return image
    return {}
