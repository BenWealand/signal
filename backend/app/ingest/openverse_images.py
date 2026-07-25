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


_SPORTS_CONTEXT = frozenset({
    "football", "soccer", "fifa", "world", "cup", "match", "matches", "team",
    "teams", "player", "players", "goal", "tournament", "league", "final",
    "finals", "playoff", "playoffs", "olympic", "olympics", "cricket", "rugby",
    "tennis", "basketball", "baseball", "hockey", "stadium", "coach",
})
_POLITICS_CONTEXT = frozenset({
    "president", "prime", "minister", "election", "parliament", "congress",
    "government", "vote", "summit", "diplomat", "sanctions", "leader",
    "cabinet", "senate", "policy", "campaign",
})
_BROAD_TOPIC_TERMS = frozenset({
    "economy", "economies", "markets", "market", "politics", "political",
    "technology", "tech", "climate", "health", "healthcare", "education",
    "sports", "sport", "business", "finance", "financial", "rates", "interest",
    "budget", "policy", "news", "update", "updates", "crisis", "conflict",
    "war", "country", "city", "world", "global", "national", "international",
    "inflation", "recession", "trade", "energy", "oil", "gas", "banking",
    "stocks", "stock", "crypto", "ai", "artificial", "intelligence", "football",
    "soccer", "baseball", "basketball", "hockey", "tennis", "change", "changes",
    "issue", "issues", "industry", "sector", "sectors", "story", "report",
    "coverage", "analysis", "review", "briefing", "developments", "development",
    "athletics", "leagues", "league", "championships", "championship", "olympic",
    "olympics", "games", "semiconductor", "semiconductors", "cybersecurity",
    "diplomacy", "affairs", "legislation", "government", "congress", "senate",
    "renewable", "weather", "environment", "breaking", "latest", "public",
    "impact", "policy", "updates",
})
_GENERIC_IMAGE_TERMS = _BROAD_TOPIC_TERMS | _WEAK_ALONE_TERMS | _STOPWORDS


_PLACE_NAME_PREFIXES = frozenset({
    "new", "north", "south", "east", "west", "saudi", "united", "hong", "sri",
    "el", "la", "las", "los", "san", "santa", "st", "saint",
})


def _looks_like_bare_place_query(value: str) -> bool:
    """True for bare place names that need concrete visual expansion.

    Single tokens ("Spain") and common place compounds ("New Jersey", "South Korea")
    count. Two-token people names ("Jerome Powell") do not — those are already
    specific enough for Openverse.
    """
    cleaned = _clean_text(value, 80)
    words = [w for w in cleaned.split() if w.lower().strip("\"'") not in _STOPWORDS]
    if len(words) == 1:
        return True
    if len(words) == 2 and words[0].lower().strip("\"'") in _PLACE_NAME_PREFIXES:
        return True
    return False


def _is_broad_image_query(value: str) -> bool:
    """Reject topic-only searches that are too vague for Openverse."""
    cleaned = _clean_text(value, 100).strip('"')
    keywords = _keywords(cleaned)
    if not keywords:
        return True
    # Every content word is a generic theme/weak sports word ("interest rates").
    if keywords <= _GENERIC_IMAGE_TERMS:
        return True
    words = [w for w in cleaned.split() if w.lower().strip("\"'") not in _STOPWORDS]
    # Single-token queries are almost always too broad ("Spain", "economy").
    # Multi-word proper names ("Jerome Powell") and concrete visuals pass.
    if len(words) == 1:
        return True
    return False


def is_broad_topic_prompt(value: str) -> bool:
    """True for keyword-bag desk prompts that are too vague to image directly.

    Section auto-generation historically used bags like
    \"stock market economy financial inflation interest rates\". Those should
    not drive Openverse search; prefer concrete source headlines or the
    finished article instead.
    """
    cleaned = _clean_text(value, 300)
    if not cleaned:
        return True
    if _is_broad_image_query(cleaned):
        return True
    keywords = _keywords(cleaned)
    if len(keywords) < 3:
        return False
    generic = keywords & _GENERIC_IMAGE_TERMS
    # Mostly theme/weak words with little distinctive subject content.
    return (len(generic) / len(keywords)) >= 0.6


def concrete_place_queries(place: str, article_text: str = "") -> list[str]:
    """Expand a bare country/city into photographic Openverse queries."""
    name = _clean_text(place, 80).strip('"')
    if not name:
        return []
    # Topic words are not places — do not invent "economy flag" style queries.
    if _keywords(name) <= _GENERIC_IMAGE_TERMS:
        return []
    article_kw = _keywords(article_text)
    raw: list[str] = []
    if article_kw & _SPORTS_CONTEXT:
        raw.extend([
            f"{name} national football team",
            f"{name} football players",
            f"{name} flag",
        ])
    elif article_kw & _POLITICS_CONTEXT:
        raw.extend([
            f"{name} prime minister",
            f"{name} president",
            f"{name} flag",
        ])
    else:
        raw.extend([
            f"{name} flag",
            f"{name} leader",
            f"{name} national team",
        ])

    queries: list[str] = []
    for item in raw:
        formatted = _format_entity_query(item) or item
        if formatted and formatted not in queries and not _is_broad_image_query(formatted):
            queries.append(formatted)
    return queries[:3]


def normalize_image_search_subjects(
    raw_queries: list[str],
    article_text: str = "",
) -> list[str]:
    """Turn broad queries into concrete photographic subjects when possible."""
    subjects: list[str] = []
    for raw in raw_queries:
        cleaned = _clean_text(raw, 100)
        if not cleaned:
            continue
        if _keywords(cleaned) <= _GENERIC_IMAGE_TERMS:
            continue
        if _looks_like_bare_place_query(cleaned):
            for item in concrete_place_queries(cleaned, article_text):
                if item not in subjects:
                    subjects.append(item)
            continue
        formatted = _format_entity_query(cleaned) or cleaned
        if not formatted or _is_broad_image_query(formatted):
            continue
        if formatted not in subjects:
            subjects.append(formatted)
    return subjects


def priority_image_queries(text: str) -> list[str]:
    """Ordered Openverse subjects: people → event → org → place → product → law → date."""
    by_type: dict[str, list[str]] = {label: [] for label in _IMAGE_ENTITY_PRIORITY}
    for entity in extract_entities(text or ""):
        label = str(entity.get("type") or "").upper()
        if label not in by_type:
            continue
        entity_text = str(entity.get("text") or "")
        if label == "GPE":
            for query in concrete_place_queries(entity_text, text or ""):
                if query not in by_type[label]:
                    by_type[label].append(query)
            continue
        query = _format_entity_query(entity_text)
        if query and not _is_broad_image_query(query) and query not in by_type[label]:
            by_type[label].append(query)

    subjects: list[str] = []
    for label in _IMAGE_ENTITY_PRIORITY:
        limit = 3 if label == "GPE" else 1
        for query in by_type[label][:limit]:
            if query not in subjects and not _is_broad_image_query(query):
                subjects.append(query)

    fallback = _search_query(text or "")
    if fallback and fallback not in subjects:
        bare = fallback.strip('"')
        if _looks_like_bare_place_query(bare):
            for query in concrete_place_queries(bare, text or ""):
                if query not in subjects and not _is_broad_image_query(query):
                    subjects.append(query)
        elif not _is_broad_image_query(fallback):
            fallback_keywords = _keywords(fallback)
            covered: set[str] = set()
            for subject in subjects:
                covered |= _keywords(subject)
            uncovered = fallback_keywords - covered
            if not subjects or len(uncovered) >= 2:
                subjects.append(fallback)
    return subjects


def image_still_fits_article(image: dict[str, Any], article_text: str) -> bool:
    """Quick safeguard: keep an already-chosen image only if it still matches."""
    if not image:
        return False
    topic = _clean_text(article_text, 800)
    article_keywords = _keywords(topic)
    if not article_keywords:
        return False
    score = candidate_title_relevance(
        {
            "title": image.get("title") or image.get("alt") or "",
            "tags": [],
            "width": 1600,
            "height": 900,
        },
        article_keywords,
        article_text=topic,
        entity_phrases=article_entity_phrases(topic),
    )
    return score >= 0


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
    *,
    article_keywords: frozenset[str] | None = None,
) -> tuple[str, str] | None:
    """Return the highest-priority article entity found in the image title."""
    if not title or not entity_phrases:
        return None
    title_keywords = _keywords(title)
    for label, text in entity_phrases:
        if not _contains_entity_phrase(title, text):
            continue
        phrase_keywords = _keywords(text)
        # Bare country/city titles ("Spain") are too weak even with an exact GPE hit.
        if label == "GPE":
            extra = (title_keywords - phrase_keywords) & (article_keywords or frozenset())
            if not (extra - _WEAK_ALONE_TERMS):
                continue
        return label, text
    return None


def _is_place_only_title(
    title_keywords: frozenset[str],
    entity_phrases: list[tuple[str, str]] | None,
) -> bool:
    """True when the title is basically just a place name from the article."""
    if not title_keywords or not entity_phrases:
        return False
    place_keywords: set[str] = set()
    for label, text in entity_phrases:
        if label == "GPE":
            place_keywords |= _keywords(text)
    if not place_keywords:
        return False
    return not (title_keywords - place_keywords - _WEAK_ALONE_TERMS)


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

    if _is_place_only_title(title_keywords, phrases):
        return -1.0

    entity_hit = best_entity_title_match(
        title,
        phrases,
        article_keywords=article_keywords,
    )

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
    preferred_queries: list[str] | None = None,
    preferred_only: bool = False,
) -> dict[str, Any]:
    """Return one relevant, attribution-ready open image or an empty dict.

    preferred_queries (for example Gemini-specific suggestions) are tried
    before NER subjects. Broad topic-only queries are skipped. Candidates are
    accepted only when their titles align with the article topic; otherwise the
    article publishes without an image.
    """
    article_text = _clean_text(topic or query, 500)
    article_keywords = _keywords(article_text)
    subjects: list[str] = []
    preferred = normalize_image_search_subjects(list(preferred_queries or []), article_text)
    for subject in preferred:
        if subject not in subjects and not _is_broad_image_query(subject):
            subjects.append(subject)
    # Fall back to specific NER subjects when Gemini gave nothing usable.
    if not (preferred_only and preferred):
        for subject in priority_image_queries(article_text or query):
            if subject not in subjects and not _is_broad_image_query(subject):
                subjects.append(subject)
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
    """Pick an Openverse image from Gemini ideas after the article is written."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        search_timeout: float = 16.0,
        min_chars: int = 100,
    ) -> None:
        self.enabled = enabled
        self.search_timeout = max(1.0, float(search_timeout))
        self.min_chars = max(40, int(min_chars))
        self._executor: ThreadPoolExecutor | None = None
        self._future = None
        self._image: dict[str, Any] = {}
        self._prompt = ""
        self._gemini_queries: list[str] = []
        self._primed = False
        self._deferred = False
        self._lock = threading.Lock()

    def _ensure_executor(self) -> ThreadPoolExecutor:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="article-image")
        return self._executor

    @staticmethod
    def topic_from_parts(headline: str = "", dek: str = "", body: str = "") -> str:
        parts = [str(headline or "").strip(), str(dek or "").strip(), str(body or "").strip()]
        return _clean_text(" ".join(part for part in parts if part), 800)

    @staticmethod
    def _topic_for_image_search(prompt: str, source_hints: list[str] | None = None) -> str:
        cleaned = _clean_text(prompt, 500)
        hints = [
            _clean_text(hint, 160)
            for hint in (source_hints or [])
            if _clean_text(hint, 160) and not is_broad_topic_prompt(_clean_text(hint, 160))
        ]
        if hints and (not cleaned or is_broad_topic_prompt(cleaned)):
            return " ".join(hints[:3])
        return cleaned

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

    def _search_from_prompt(self) -> dict[str, Any]:
        """Optional warm-up search from the topic while the article writes."""
        preferred: list[str] = []
        try:
            from app.llm.gemini_writer import suggest_image_queries_with_gemini

            preferred = suggest_image_queries_with_gemini(
                headline=self._prompt,
                dek="",
                body_paragraphs=[],
                topic=self._prompt,
                max_queries=3,
            ) or []
        except Exception:
            logger.exception("Gemini prompt image-subject suggestion failed")
            preferred = []
        self._gemini_queries = list(preferred)
        return find_openverse_image(
            self._prompt,
            topic=self._prompt,
            preferred_queries=preferred,
            preferred_only=bool(preferred),
            timeout=self.search_timeout,
        ) or {}

    def prime_from_prompt(
        self,
        prompt: str,
        *,
        source_hints: list[str] | None = None,
    ) -> None:
        """Optionally warm up Openverse while the article writes.

        The authoritative pick still happens in finalize() after Gemini reads the
        finished article and proposes its top image ideas.
        """
        if not self.enabled:
            return
        topic = self._topic_for_image_search(prompt, source_hints)
        if len(topic) < 8:
            return
        with self._lock:
            if self._primed or self._image:
                return
            self._primed = True
            self._prompt = topic
            # Defer Openverse until finalize when we still only have a broad bag.
            if is_broad_topic_prompt(topic):
                self._deferred = True
                return
            self._deferred = False
            executor = self._ensure_executor()
            self._future = executor.submit(self._search_from_prompt)

    def on_chunk(self, progress: dict[str, Any] | None) -> None:
        """Streaming drafts are not used for Openverse searches."""
        return

    def finalize(
        self,
        *,
        headline: str = "",
        dek: str = "",
        body: str | list[str] = "",
        wait_seconds: float = 8.0,
    ) -> dict[str, Any]:
        """After the article is written: Gemini top-5 ideas, then try each."""
        if not self.enabled:
            self.shutdown()
            return {}

        body_text = body if isinstance(body, str) else " ".join(str(part) for part in body)
        topic = self.topic_from_parts(headline, dek, body_text) or self._prompt
        with self._lock:
            self._collect_finished()
            if not self._image and self._future:
                future = self._future
            else:
                future = None

        # Don't block long on the warm-up; the finished-article pass is primary.
        if future:
            try:
                result = future.result(timeout=min(1.0, max(0.0, float(wait_seconds)))) or {}
                if result:
                    with self._lock:
                        if not self._image:
                            self._image = dict(result)
            except TimeoutError:
                logger.info("Warm-up article image still pending; continuing with finished-article ideas")
            except Exception:
                logger.exception("Warm-up article image lookup failed")

        with self._lock:
            warm_image = dict(self._image) if self._image else {}

        if not topic or len(topic) < min(self.min_chars, 40):
            self.shutdown()
            return warm_image if warm_image and image_still_fits_article(warm_image, topic or self._prompt) else {}

        body_parts = body if isinstance(body, list) else [body_text]
        article_queries: list[str] = []
        try:
            from app.llm.gemini_writer import suggest_image_queries_with_gemini

            article_queries = suggest_image_queries_with_gemini(
                headline=headline or self._prompt,
                dek=dek,
                body_paragraphs=[str(part) for part in body_parts if str(part).strip()],
                topic=headline or self._prompt,
                max_queries=5,
            ) or []
            self._gemini_queries = list(article_queries)
        except Exception:
            logger.exception("Gemini finished-article image ideas failed")
            article_queries = []

        image: dict[str, Any] = {}
        if article_queries:
            try:
                image = find_openverse_image(
                    topic,
                    topic=topic,
                    preferred_queries=article_queries,
                    preferred_only=True,
                    timeout=self.search_timeout,
                ) or {}
            except Exception:
                logger.exception("Finished-article Openverse search failed")
                image = {}

        if image:
            self.shutdown()
            return dict(image)

        # Warm-up fallback only if it still matches the finished article.
        if warm_image and image_still_fits_article(warm_image, topic):
            self.shutdown()
            return warm_image

        # Last resort: NER subjects from the finished article.
        try:
            image = find_openverse_image(
                topic,
                topic=topic,
                preferred_queries=article_queries or None,
                preferred_only=False,
                timeout=max(2.0, float(wait_seconds)),
            ) or {}
        except Exception:
            logger.exception("Fallback article image lookup failed")
            image = {}
        self.shutdown()
        return dict(image)

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
