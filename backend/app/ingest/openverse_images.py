from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any

from app.nlp.ner import extract_entities

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.openverse.org/v1/images/"
_ALLOWED_LICENSES = frozenset({"by", "by-sa", "cc0", "pdm"})
_ALLOWED_FILE_TYPES = frozenset({"jpg", "jpeg", "png", "webp"})
# Prefer visually concrete subjects first when choosing an Openverse query.
_IMAGE_ENTITY_PRIORITY = ("PERSON", "EVENT", "ORG", "GPE", "PRODUCT", "LAW", "DATE")
# Exact title matches for these types are strong enough to keep a candidate
# even when the filename/title has extra filler words.
_ENTITY_TITLE_MATCH_TYPES = frozenset({"PERSON", "EVENT", "ORG", "GPE", "PRODUCT", "LAW"})
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "is", "was",
    "at", "to", "from", "with", "by", "that", "this", "it", "its", "be",
    "are", "were", "has", "have", "had", "as", "new", "will", "more",
    "said", "says", "about", "after", "over", "into", "also", "than",
    "latest", "update", "updates", "news", "review", "cross", "source",
    "what", "when", "where", "why", "how", "who", "happened", "happens",
})
# Generic words that must not be the only link between an image title and an article.
_WEAK_ALONE_TERMS = frozenset({
    "league", "football", "soccer", "rugby", "baseball", "basketball", "hockey",
    "game", "games", "match", "matches", "team", "teams", "sport", "sports",
    "player", "players", "final", "finals", "cup", "ball", "field", "stadium",
    "press", "photo", "photograph", "photography", "image", "picture", "pictures",
    "celebrity", "celebrities", "event", "events", "day", "night", "city", "club",
    "season", "championship", "tournament", "score", "scores", "win", "wins",
    "official", "portrait", "crop", "cropped", "visit", "meeting", "summit",
})
_LOW_VALUE_IMAGE_TERMS = frozenset({
    "logo", "icon", "wordmark", "watermark", "placeholder", "avatar", "emoji",
})
# Reject these title terms unless the article itself uses them.
_SENSITIVE_TITLE_TERMS = frozenset({
    "lingerie", "nude", "nudes", "sexy", "erotic", "porn", "nsfw", "bikini",
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
        if meaningful >= 3:
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
        fallback_keywords = _keywords(fallback)
        covered: set[str] = set()
        for subject in subjects:
            covered |= _keywords(subject)
        uncovered = fallback_keywords - covered
        # Keep the prompt phrase only when it adds real topical terms we do not
        # already plan to search, or when NER found nothing usable.
        if not subjects or len(uncovered) >= 2:
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


def _contains_phrase(haystack: str, needle: str) -> bool:
    left = re.sub(r"\s+", " ", (haystack or "").lower()).strip()
    right = re.sub(r"\s+", " ", (needle or "").lower()).strip(" \"'")
    if not left or not right or len(right) < 5:
        return False
    return right in left


def _normalize_match_text(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def _contains_entity_phrase(title: str, entity: str) -> bool:
    """True when the image title contains the entity as a whole phrase."""
    title_norm = f" {_normalize_match_text(title)} "
    entity_norm = _normalize_match_text(entity)
    if len(entity_norm) < 3:
        return False
    return f" {entity_norm} " in title_norm


def _entity_is_specific(entity_text: str) -> bool:
    keywords = _keywords(entity_text)
    if not keywords:
        return False
    distinctive = keywords - _WEAK_ALONE_TERMS
    if distinctive:
        return True
    # Allow multi-word weak phrases only when they are long enough to be specific
    # ("Premier League"), but not bare "League".
    return len(keywords) >= 2 and len(_normalize_match_text(entity_text)) >= 10


def article_entity_phrases(article_text: str) -> list[tuple[str, str]]:
    """Return (type, text) entity phrases usable for exact title matching."""
    by_type: dict[str, list[str]] = {label: [] for label in _IMAGE_ENTITY_PRIORITY}
    for entity in extract_entities(article_text or ""):
        label = str(entity.get("type") or "").upper()
        if label not in _ENTITY_TITLE_MATCH_TYPES:
            continue
        text = _clean_text(entity.get("text"), 120)
        if not text or not _entity_is_specific(text):
            continue
        if text not in by_type[label]:
            by_type[label].append(text)

    phrases: list[tuple[str, str]] = []
    seen: set[str] = set()
    for label in _IMAGE_ENTITY_PRIORITY:
        if label not in _ENTITY_TITLE_MATCH_TYPES:
            continue
        for text in by_type[label]:
            key = _normalize_match_text(text)
            if not key or key in seen:
                continue
            seen.add(key)
            phrases.append((label, text))
    return phrases


def best_entity_title_match(
    title: str,
    entity_phrases: list[tuple[str, str]] | None,
) -> tuple[str, str] | None:
    """Return the highest-priority article entity found in the image title."""
    if not title or not entity_phrases:
        return None
    for label, text in entity_phrases:
        if _contains_entity_phrase(title, text):
            return label, text
    return None


def candidate_title_relevance(
    item: dict[str, Any],
    article_keywords: frozenset[str],
    *,
    article_text: str = "",
    entity_phrases: list[tuple[str, str]] | None = None,
) -> float:
    """Score how well an image title matches the article; -1 means reject."""
    title = _clean_text(item.get("title"))
    title_keywords = _keywords(title)
    if not title_keywords or not article_keywords:
        return -1.0
    if title_keywords & _LOW_VALUE_IMAGE_TERMS:
        return -1.0

    sensitive = title_keywords & _SENSITIVE_TITLE_TERMS
    if sensitive and not (sensitive & article_keywords):
        return -1.0

    phrases = entity_phrases
    if phrases is None and article_text:
        phrases = article_entity_phrases(article_text)
    entity_hit = best_entity_title_match(title, phrases)

    width = _safe_int(item.get("width"))
    height = _safe_int(item.get("height"))
    if width and height:
        if width < 640 or height < 360:
            return -1.0
        ratio = width / height
        if ratio < 1.15 or ratio > 2.6:
            return -1.0

    # Exact person / org / place / product / event / law match in the title is
    # enough even when the title also has filler words ("official portrait of …").
    if entity_hit:
        label, phrase = entity_hit
        priority_bonus = max(1, len(_IMAGE_ENTITY_PRIORITY) - _IMAGE_ENTITY_PRIORITY.index(label)) * 3.0
        phrase_keywords = _keywords(phrase)
        return (
            24.0
            + priority_bonus
            + len(phrase_keywords) * 2.0
            + (1.0 if width >= 1200 else 0.0)
        )

    title_overlap = title_keywords & article_keywords
    if not title_overlap:
        return -1.0

    distinctive = title_overlap - _WEAK_ALONE_TERMS
    # A single generic word like "league" or "football" is not enough.
    if not distinctive and len(title_overlap) < 2:
        return -1.0

    # Most of the title's content words should also appear in the article.
    title_precision = len(title_overlap) / max(1, len(title_keywords))
    if title_precision < 0.5:
        return -1.0
    # If half the title is off-topic, demand a distinctive shared term.
    if title_precision < 0.67 and not distinctive:
        return -1.0

    tag_overlap = _keywords(_tag_text(item)) & article_keywords
    phrase_bonus = 0.0
    # Reward titles that literally contain a multi-word article subject span.
    for span in re.findall(r"\b[A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+){1,3}\b", article_text or ""):
        if _contains_phrase(title, span):
            phrase_bonus += 3.0
            break

    return (
        len(distinctive) * 4.0
        + len(title_overlap) * 2.0
        + title_precision * 6.0
        + min(2.0, len(tag_overlap) * 0.25)
        + phrase_bonus
        + (1.0 if width >= 1200 else 0.0)
    )


def _candidate_score(
    item: dict[str, Any],
    article_keywords: frozenset[str],
    *,
    article_text: str = "",
    entity_phrases: list[tuple[str, str]] | None = None,
) -> float:
    return candidate_title_relevance(
        item,
        article_keywords,
        article_text=article_text,
        entity_phrases=entity_phrases,
    )


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


def _lookup_openverse_image(
    clean_query: str,
    *,
    article_keywords: frozenset[str],
    article_text: str,
    timeout: float,
) -> dict[str, Any]:
    """Return one ranked Openverse match for a prepared subject query, or {}."""
    query_keywords = _keywords(clean_query)
    if not clean_query or not query_keywords or not article_keywords:
        return {}

    topic_fingerprint = ".".join(sorted(article_keywords)[:24])
    cache_key = f"{clean_query.lower()}::{topic_fingerprint}"
    now = time.monotonic()
    with _cache_lock:
        cached = _image_cache.get(cache_key)
        if cached and cached[0] > now:
            return dict(cached[1])

    params = urllib.parse.urlencode({
        "q": clean_query,
        "page_size": 20,
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

    entity_phrases = article_entity_phrases(article_text)
    scored: list[tuple[float, dict[str, Any]]] = []
    results = (payload.get("results") or []) if isinstance(payload, dict) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_image(item, clean_query)
        if not normalized:
            continue
        score = _candidate_score(
            item,
            article_keywords,
            article_text=article_text,
            entity_phrases=entity_phrases,
        )
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


def find_openverse_image(
    query: str,
    *,
    timeout: float = 8.0,
    topic: str | None = None,
) -> dict[str, Any]:
    """Return one relevant, attribution-ready open image or an empty dict.

    Search subjects prefer NER spans in this order: PERSON, EVENT, ORG, GPE,
    PRODUCT, LAW, DATE. Candidates are accepted only when their titles align
    with the article topic; otherwise the article publishes without an image.
    """
    article_text = _clean_text(topic or query, 500)
    article_keywords = _keywords(article_text)
    subjects = priority_image_queries(article_text or query)
    if not subjects or not article_keywords:
        return {}

    deadline = time.monotonic() + max(1.0, float(timeout))
    for index, subject in enumerate(subjects):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        # Leave a little budget for later priority subjects when several remain.
        later = len(subjects) - index - 1
        per_try = remaining if later <= 0 else max(0.75, remaining / (later + 1))
        image = _lookup_openverse_image(
            subject,
            article_keywords=article_keywords,
            article_text=article_text,
            timeout=per_try,
        )
        if image:
            return image
    return {}


class ArticleImagePicker:
    """Kick off Openverse lookups from streamed article text before publish."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        search_timeout: float = 8.0,
        min_chars: int = 100,
    ) -> None:
        self.enabled = enabled
        self.search_timeout = max(1.0, float(search_timeout))
        self.min_chars = max(40, int(min_chars))
        self._executor: ThreadPoolExecutor | None = None
        self._future = None
        self._image: dict[str, Any] = {}
        self._last_topic = ""
        self._lock = threading.Lock()

    def _ensure_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="article-image")
        return self._executor

    @staticmethod
    def topic_from_parts(headline: str = "", dek: str = "", body: str = "") -> str:
        parts = [str(headline or "").strip(), str(dek or "").strip(), str(body or "").strip()]
        return _clean_text(" ".join(part for part in parts if part), 800)

    def _collect_finished(self) -> None:
        future = self._future
        if not future or not future.done():
            return
        try:
            result = future.result(timeout=0) or {}
        except Exception:
            result = {}
        self._future = None
        if result and not self._image:
            self._image = dict(result)

    def consider(self, headline: str = "", dek: str = "", body: str = "") -> None:
        """Start/refresh an image search once enough article draft text exists."""
        if not self.enabled:
            return
        topic = self.topic_from_parts(headline, dek, body)
        if len(topic) < self.min_chars:
            return
        with self._lock:
            self._collect_finished()
            if self._image:
                return
            if self._future and not self._future.done():
                return
            # Avoid re-querying nearly identical draft snapshots.
            if self._last_topic and topic.startswith(self._last_topic[: max(80, len(self._last_topic) // 2)]):
                if abs(len(topic) - len(self._last_topic)) < 80 and priority_image_queries(topic) == priority_image_queries(self._last_topic):
                    return
            self._last_topic = topic
            executor = self._ensure_executor()
            self._future = executor.submit(
                find_openverse_image,
                topic,
                topic=topic,
                timeout=self.search_timeout,
            )

    def on_chunk(self, progress: dict[str, Any] | None) -> None:
        payload = progress or {}
        self.consider(
            headline=str(payload.get("headline") or ""),
            dek=str(payload.get("dek") or ""),
            body=str(payload.get("draft_text") or ""),
        )

    def finalize(
        self,
        *,
        headline: str = "",
        dek: str = "",
        body: str | list[str] = "",
        wait_seconds: float = 4.0,
    ) -> dict[str, Any]:
        """Wait for any in-flight lookup, then one last pass on the finished article."""
        if not self.enabled:
            self.shutdown()
            return {}

        body_text = body if isinstance(body, str) else " ".join(str(part) for part in body)
        topic = self.topic_from_parts(headline, dek, body_text)
        with self._lock:
            self._collect_finished()
            if not self._image and self._future:
                future = self._future
            else:
                future = None

        if future:
            try:
                result = future.result(timeout=max(0.0, float(wait_seconds))) or {}
                if result:
                    with self._lock:
                        if not self._image:
                            self._image = dict(result)
            except TimeoutError:
                logger.info("Article image lookup still pending; trying a final pass")
            except Exception:
                logger.exception("Article image lookup failed")

        with self._lock:
            image = dict(self._image) if self._image else {}

        if image:
            self.shutdown()
            return image

        if topic and len(topic) >= self.min_chars:
            try:
                image = find_openverse_image(
                    topic,
                    topic=topic,
                    timeout=min(self.search_timeout, max(1.0, float(wait_seconds) + 1.5)),
                ) or {}
            except Exception:
                logger.exception("Final article image lookup failed")
                image = {}
            self.shutdown()
            return dict(image)

        self.shutdown()
        return {}

    def shutdown(self) -> None:
        with self._lock:
            future = self._future
            executor = self._executor
            self._future = None
            self._executor = None
        if future and not future.done():
            future.cancel()
        if executor:
            executor.shutdown(wait=False, cancel_futures=True)
