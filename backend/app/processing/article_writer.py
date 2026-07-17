from __future__ import annotations

import re
import time
import threading
import uuid
import logging
from datetime import datetime, timezone

from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

logger = logging.getLogger(__name__)

# ── Build progress tracker ─────────────────────────────────────────────────────
# Lightweight global state updated at each pipeline stage.
# The /articles/progress endpoint reads this to stream live status to the UI.

_progress_lock = threading.Lock()
_default_progress: dict = {
    "active": False,
    "build_id": "",
    "prompt": "",
    "stage": "idle",
    "stage_label": "Waiting",
    "sources_found": 0,
    "sources_enriched": 0,
    "claims_extracted": 0,
    "started_at": 0.0,
    "elapsed_s": 0,
    "draft_text": "",
    "draft_headline": "",
    "article": None,
    "error": None,
}
_progress: dict = dict(_default_progress)
_progress_by_build: dict[str, dict] = {}
_latest_build_id = ""


def get_build_progress(build_id: str | None = None) -> dict:
    with _progress_lock:
        if build_id:
            p = dict(_progress_by_build.get(build_id) or {**_default_progress, "build_id": build_id, "stage_label": "Unknown build"})
        elif _latest_build_id and _latest_build_id in _progress_by_build:
            p = dict(_progress_by_build[_latest_build_id])
        else:
            p = dict(_progress)
    if p["active"] and p["started_at"]:
        p["elapsed_s"] = int(time.time() - p["started_at"])
    return p


def _set_progress(build_id: str | None = None, **kwargs: object) -> None:
    global _latest_build_id
    with _progress_lock:
        target = _progress
        if build_id:
            _latest_build_id = build_id
            target = _progress_by_build.setdefault(build_id, {**_default_progress, "build_id": build_id})
        target.update(kwargs)
        if build_id:
            target["build_id"] = build_id
        if kwargs.get("active") and "started_at" not in kwargs:
            target["started_at"] = time.time()
        _progress.update(target)


set_build_progress = _set_progress

from app.db import queries
from app.ingest.article_reader import fetch_readable_article_text
from app.ingest.gdelt_ingest import fetch_gdelt_articles
from app.ingest.openverse_images import find_openverse_image
from app.ingest.rss_ingest import fetch_articles_for_query_fast
from app.ingest.source_registry import domain_from_url, is_blocked_domain
from app.ingest.source_ranker import SourceGate, evaluate_source_quality, rank_sources
from app.config import settings
from app.llm.consensus import detect_consensus
from app.llm.trend_article import title_case
from app.nlp.ner import extract_entities
from app.processing.clean_text import clean_article_text
from app.llm.claim_extractor import extract_claims


THOROUGH_SOURCE_GATE = SourceGate(min_sources=3, min_domains=2, min_text_chars=180, max_current_age_days=14)


class GeminiArticleUnavailable(RuntimeError):
    """Raised when an article cannot be written by Gemini."""


# ── Language / relevance helpers ──────────────────────────────────────────────

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "in", "on", "for", "is", "was",
    "at", "to", "from", "with", "by", "that", "this", "it", "its", "be",
    "are", "were", "has", "have", "had", "as", "new", "will", "more",
    "said", "says", "about", "after", "over", "into", "also", "than",
    "its", "but", "not", "their", "they", "been", "would", "could",
})


def _prompt_keywords(prompt: str) -> frozenset[str]:
    return frozenset(
        w for w in re.findall(r"[a-z]{3,}", prompt.lower())
        if w not in _STOPWORDS
    )


def _is_mostly_latin(text: str, threshold: float = 0.75) -> bool:
    """Return True if at least `threshold` fraction of letters are Latin (ASCII a-z A-Z)."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if ord(c) < 128)
    return latin / len(letters) >= threshold


def _article_keywords(article: dict) -> frozenset[str]:
    text = (
        article.get("title", "") + " " +
        article.get("clean_text", "")[:2000] + " " +
        article.get("raw_text", "")[:1000]
    ).lower()
    return frozenset(re.findall(r"[a-z]{3,}", text)) - _STOPWORDS


def _relevance_score(article: dict, prompt_kw: frozenset[str]) -> float:
    if not prompt_kw:
        return 1.0
    art_kw = _article_keywords(article)
    return len(prompt_kw & art_kw) / len(prompt_kw)


def _phrase_in_text(phrase: str, text: str) -> bool:
    """Case-insensitive check that the full phrase appears in text."""
    return phrase.lower() in text.lower()


def _is_relevant(article: dict, prompt: str, prompt_kw: frozenset[str]) -> bool:
    """
    Three-tier relevance check (strongest to weakest):

    Tier 1 — Phrase match: the full prompt string appears verbatim in the
             article title or body.  Immediately accepted.
    Tier 2 — Title phrase match: every prompt keyword appears somewhere in the
             title (order-independent).  Accepted.
    Tier 3 — Keyword overlap: title must contain ≥1 prompt keyword AND the
             overall keyword overlap must be ≥ 34% (higher than before, because
             single-word hits on common words like "supply" are not enough).

    An article is dropped if none of the three tiers pass.
    """
    if not prompt_kw:
        return True

    title = article.get("title", "").lower()
    body = (article.get("clean_text", "") + article.get("raw_text", ""))[:2000].lower()

    # Tier 1: full phrase in title or body
    if _phrase_in_text(prompt, title) or _phrase_in_text(prompt, body):
        return True

    title_kw = frozenset(re.findall(r"[a-z]{3,}", title)) - _STOPWORDS

    # Tier 2: all prompt keywords present somewhere in title (any order)
    if len(prompt_kw) >= 2 and prompt_kw.issubset(title_kw | (frozenset(re.findall(r"[a-z]{3,}", body)) - _STOPWORDS)):
        # Still require at least one keyword in the title itself
        if prompt_kw & title_kw:
            return True

    # Tier 3: higher keyword-overlap threshold (0.34 instead of 0.20)
    if not (prompt_kw & title_kw):
        return False  # title shares zero keywords → definitely unrelated
    return _relevance_score(article, prompt_kw) >= 0.34


def _filter_relevant(articles: list[dict], prompt: str) -> list[dict]:
    """
    Apply `_is_relevant` to each article.
    If nothing passes, fall back to Tier-3-only with a relaxed threshold (0.20),
    but still require at least one keyword in the title.
    """
    prompt_kw = _prompt_keywords(prompt)
    if not prompt_kw:
        return articles

    strict = [a for a in articles if _is_relevant(a, prompt, prompt_kw)]
    if strict:
        return strict

    # Soft fallback — at least one title keyword, lower overlap bar
    relaxed = [
        a for a in articles
        if (prompt_kw & (frozenset(re.findall(r"[a-z]{3,}", a.get("title", "").lower())) - _STOPWORDS))
        and _relevance_score(a, prompt_kw) >= 0.20
    ]
    return relaxed  # empty is fine — caller generates a "no results" fallback


# ── Article processing ────────────────────────────────────────────────────────

def _parallel_process(articles: list[dict]) -> list[dict]:
    """
    Insert all articles into DB, then process (clean text, entities, claims)
    for all of them in parallel using a thread pool.
    Returns the list of processed article dicts fetched fresh from DB.
    """
    # Insert first (sequential — DB writes shouldn't be threaded)
    id_map: dict[int, dict] = {}
    for a in articles:
        if a.get("raw_text"):
            aid = queries.insert_article(a)
            id_map[aid] = a

    if not id_map:
        return []

    # Process in parallel
    def _proc(aid: int) -> dict | None:
        article = queries.get_article(aid)
        if article:
            _process_article(article)
            return queries.get_article(aid)
        return None

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(len(id_map), 16)) as pool:
        futures = {pool.submit(_proc, aid): aid for aid in id_map}
        for future in as_completed(futures):
            result = future.result()
            if result and result.get("status") == "processed":
                results.append(result)

    return results


def _process_article(article: dict) -> None:
    if article.get("duplicate_of"):
        queries.update_article_processing(int(article["id"]), article.get("clean_text") or "", "duplicate")
        return
    raw = str(article["raw_text"])
    if not _is_mostly_latin(raw):
        # Non-Latin article (Chinese, Arabic, etc.) — mark processed but skip claims
        queries.update_article_processing(int(article["id"]), "", "processed")
        return
    clean_text = clean_article_text(raw)
    entities = extract_entities(clean_text)
    entity_names = [str(e["text"]) for e in entities]
    claims = extract_claims(clean_text, entities=entity_names)
    queries.update_article_processing(int(article["id"]), clean_text, "processed")
    queries.replace_entities(int(article["id"]), entities)
    queries.replace_claims(int(article["id"]), claims)


def _enrich_candidate(candidate: dict) -> dict:
    readable = fetch_readable_article_text(candidate.get("url", ""), fallback=candidate.get("raw_text", ""))
    return {**candidate, "raw_text": readable or candidate.get("raw_text", "")}


def _cached_articles_for_prompt(prompt: str, limit: int) -> list[dict]:
    """
    Search the DB for articles relevant to this prompt.

    Prefer the last 2 days of desk coverage first, then broaden. Search order:
    1. Full phrase match in recent window
    2. Full phrase match overall
    3. Longest meaningful sub-phrases (pairs of adjacent keywords)
    4. Individual keywords that are ≥6 chars (less noise than short words)

    Every candidate is passed through _is_relevant before being added,
    so unrelated articles that happen to contain a common word are dropped.
    """
    prompt_kw = _prompt_keywords(prompt)
    found: dict[int, dict] = {}

    def _add(result_list: list) -> None:
        for result in result_list:
            if len(found) >= limit * 3:
                return
            article_id = int(result["id"])
            if article_id in found:
                continue
            # search() already returns enough fields for Fast mode; avoid a
            # second round-trip when the row already has usable text.
            if result.get("raw_text") or result.get("clean_text") or result.get("description"):
                candidate = result
            else:
                candidate = queries.get_article(article_id)
            if candidate and _is_relevant(candidate, prompt, prompt_kw):
                if not candidate.get("raw_text"):
                    candidate = {
                        **candidate,
                        "raw_text": candidate.get("clean_text") or candidate.get("description") or "",
                    }
                found[article_id] = candidate

    # 1. Recent desk cache (daily ingest window)
    _add(queries.search(prompt, days=2, limit=max(limit * 2, 12)))

    # 2. Full phrase across all ages
    if len(found) < limit:
        _add(queries.search(prompt, limit=max(limit * 2, 12)))

    if len(found) < limit:
        words = [w for w in prompt.split() if len(w) >= 4 and w.lower() not in _STOPWORDS]

        # 3. Adjacent-word bigrams  ("supply chain", "chain hack")
        for i in range(len(words) - 1):
            bigram = f"{words[i]} {words[i+1]}"
            _add(queries.search(bigram, days=2, limit=10))
            if len(found) >= limit:
                break
            _add(queries.search(bigram, limit=10))
            if len(found) >= limit:
                break

        # 4. Long individual keywords only (≥6 chars reduces noise)
        if len(found) < limit:
            for term in [w for w in words if len(w) >= 6][:3]:
                _add(queries.search(term, days=2, limit=8))
                if len(found) >= limit:
                    break
                _add(queries.search(term, limit=8))

    return list(found.values())[:limit]


# ── Article synthesis ──────────────────────────────────────────────────────────

def _best_headline(prompt: str, supported: list[dict], source_articles: list[dict]) -> str:
    """
    Pick a headline that is actually about the prompt topic.
    Prefer a supported claim text, then a source title that shares keywords
    with the prompt. Fall back to a formatted version of the prompt itself.
    """
    prompt_words = [
        word for word in re.findall(r"[a-z0-9#]+", prompt.lower())
        if len(word) >= 3 and word not in _STOPWORDS
    ]
    topic_words = list(dict.fromkeys(prompt_words))[:7]
    if len(topic_words) < 3:
        title_terms: list[str] = []
        for article in source_articles:
            title = article.get("title", "")
            if not _is_mostly_latin(title):
                continue
            for word in re.findall(r"[a-z0-9]+", title.lower()):
                if len(word) >= 4 and word not in _STOPWORDS and word not in title_terms:
                    title_terms.append(word)
                if len(title_terms) >= 6:
                    break
            if len(title_terms) >= 6:
                break
        topic_words = topic_words + [word for word in title_terms if word not in topic_words]

    topic = title_case(" ".join(topic_words[:7]) or prompt)
    if len(supported) >= 2:
        return f"What {len(supported)} Corroborated Claims Show About {topic}"
    if len(source_articles) >= 6:
        return f"{topic} Draws Cross-Source Review"
    if topic:
        return f"Public Sources Track {topic}"
    return "Signal Coverage From Public Sources"

    prompt_kw = _prompt_keywords(prompt)

    if supported:
        text = supported[0]["claim_text"].rstrip(".")
        words = text.split()
        return text if len(words) <= 14 else " ".join(words[:14]) + "…"

    # Only use a source title if it shares ≥1 keyword with the prompt
    relevant_titles = [
        a["title"] for a in source_articles
        if len(a.get("title", "")) > 20
        and _is_mostly_latin(a.get("title", ""))
        and (prompt_kw & (frozenset(re.findall(r"[a-z]{3,}", a["title"].lower())) - _STOPWORDS))
    ]
    if relevant_titles:
        best = max(relevant_titles, key=len)
        words = best.split()
        return best if len(words) <= 16 else " ".join(words[:16]) + "…"

    return title_case(prompt) + " — Signal Coverage"


def _best_dek(source_count: int, source_names: list[str], supported: list[dict]) -> str:
    outlets = ", ".join(source_names[:4]) + (f" +{len(source_names) - 4} more" if len(source_names) > 4 else "")
    if supported:
        return f"{len(supported)} claim{'s' if len(supported) != 1 else ''} corroborated across {source_count} sources: {outlets}."
    return f"Signal compared {source_count} public sources: {outlets}." if source_names else "Signal coverage."


_BOILERPLATE = frozenset((
    "subscribe", "sign up", "cookie", "privacy policy", "all rights reserved",
    "javascript", "loading", "advertisement", "click here", "read more",
    "terms of service", "newsletter", "follow us", "get the app",
    "be sure to join me", "that's all from me", "that's about all",
    "join me tomorrow", "see you tomorrow", "thanks for following",
    "follow our live", "live blog", "minute by minute",
))

# Matches "... - Source Name" or "... — Source Name" at end of title-like strings
_TITLE_ATTRIBUTION = re.compile(r"\s[-–—]\s*[A-Z][A-Za-z ]{2,30}\s*$")


def _is_good_claim(text: str, min_len: int = 40) -> bool:
    """Return True if a claim text is worth showing to the user."""
    if len(text) < min_len:
        return False
    if not _is_mostly_latin(text, threshold=0.80):
        return False
    skip_prefixes = ("signal ", "the signal ", "according to signal")
    if any(text.lower().startswith(p) for p in skip_prefixes):
        return False
    lowered = text.lower()
    if any(p in lowered for p in _BOILERPLATE):
        return False
    # Drop claims that are plainly just article titles (end with "- Source Name")
    if _TITLE_ATTRIBUTION.search(text):
        return False
    # Drop claims where almost every word is capitalised (headline formatting)
    words = text.split()
    if len(words) >= 5:
        cap_ratio = sum(1 for w in words if w and w[0].isupper()) / len(words)
        if cap_ratio > 0.65:
            return False
    return True


def _good_claim_texts(claims: list[dict], min_len: int = 40) -> list[str]:
    out = []
    for c in claims:
        text = c.get("claim_text", "")
        if _is_good_claim(text, min_len) and text not in out:
            out.append(text)
    return out


def _extract_sentences(text: str, max_sentences: int = 3) -> list[str]:
    """
    Extract the best informational sentences from an article body.
    Skips boilerplate, navigation text, and title-like all-caps lines.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    good: list[str] = []
    for raw in sentences:
        s = raw.strip()
        if len(s) < 50 or not _is_mostly_latin(s):
            continue
        lowered = s.lower()
        if any(p in lowered for p in _BOILERPLATE):
            continue
        # Skip title-like lines (most words capitalised)
        words = s.split()
        if len(words) >= 5:
            cap_ratio = sum(1 for w in words if w and w[0].isupper()) / len(words)
            if cap_ratio > 0.60:
                continue
        good.append(s)
        if len(good) >= max_sentences:
            break
    return good


def _prose_paragraphs(source_articles: list[dict], prompt_kw: frozenset[str]) -> list[str]:
    """
    Build attributed prose paragraphs from source articles.

    For each article that has extractable body text, write a paragraph like:
      "According to [Source], Mitchell scored 39 points in the second half,
       leading the Cavaliers to a 2-2 series tie. The performance tied an
       NBA playoff record, the outlet reported."

    Falls back to a clean title-attribution sentence when no body text is
    available: "[Source] reported that Mitchell led the Cavaliers to a win."
    """
    paragraphs: list[str] = []
    seen_fingerprints: set[str] = set()

    # Richest text first
    ordered = sorted(
        source_articles,
        key=lambda a: len(a.get("clean_text", "") or a.get("raw_text", "")),
        reverse=True,
    )

    for art in ordered:
        source = (art.get("source_name") or "").strip()
        title  = (art.get("title")       or "").strip()
        clean  = (art.get("clean_text")  or art.get("raw_text") or "").strip()

        if not _is_mostly_latin(title or clean[:100]):
            continue

        # Dedup on first 40 chars of title
        fp = title[:40].lower()
        if fp in seen_fingerprints or not fp:
            continue
        seen_fingerprints.add(fp)

        # Accept any clean text with 80+ chars — even short snippets are useful
        sents = _extract_sentences(clean, max_sentences=3) if len(clean) > 80 else []

        if sents:
            # Build an attributed paragraph from extracted sentences
            core = " ".join(sents[:2])
            if source:
                para = f"According to {source}, {core[:1].lower() + core[1:]}"
                if len(sents) >= 3:
                    tail = sents[2]
                    para += f" {source} also noted that {tail[:1].lower() + tail[1:]}"
            else:
                para = core
        elif title and len(title) > 30 and _is_mostly_latin(title):
            # Fall back: attribute the title as a reported fact
            if source:
                # Lowercase the title body after "reported that ..."
                lower_title = title.rstrip(".").rstrip("?").rstrip("!")
                # Strip trailing "- Source" attribution that may be in the title
                lower_title = _TITLE_ATTRIBUTION.sub("", lower_title).strip()
                para = f"{source} reported that {lower_title[:1].lower() + lower_title[1:]}."
            else:
                para = title
        else:
            continue

        paragraphs.append(para)
        if len(paragraphs) >= 5:
            break

    return paragraphs


def _article_body(
    prompt: str,
    source_articles: list[dict],
    supported: list[dict],
    unique_claims: list[dict],
    use_gemini: bool = True,
    require_gemini: bool = False,
    *,
    generation_mode: str = "thorough",
    build_id: str | None = None,
) -> tuple[list[str], dict[str, str] | None]:
    """
    Try Gemini first for a polished, grammar-correct article package.
    Returns (body_paragraphs, optional_header_package).
    When Gemini is required, fail without saving a generated article.
    """
    from app.llm.gemini_writer import write_article_package_with_gemini

    # ── Gemini path ───────────────────────────────────────────────────────────
    package = (
        write_article_package_with_gemini(
            prompt,
            source_articles,
            mode=generation_mode,
        )
        if use_gemini
        else None
    )
    if package and package.get("body"):
        gemini_text = package["body"]
        paragraphs = [p.strip() for p in gemini_text.split("\n\n") if p.strip()]
        if len(paragraphs) < 2:
            paragraphs = [p.strip() for p in gemini_text.split("\n") if len(p.strip()) > 60]
        if len(paragraphs) >= 2:
            header = {
                "headline": str(package.get("headline") or "").strip(),
                "dek": str(package.get("dek") or "").strip(),
            }
            return paragraphs, header if header["headline"] and header["dek"] else None

    if require_gemini:
        raise GeminiArticleUnavailable("Gemini did not return a usable article draft")

    # ── Rule-based fallback ───────────────────────────────────────────────────
    prompt_kw = _prompt_keywords(prompt)
    source_names = sorted({str(a["source_name"]) for a in source_articles})
    source_count = len(source_articles)
    body: list[str] = []

    good_supported = _good_claim_texts(supported)

    if good_supported:
        body.append(good_supported[0])
    else:
        richest = max(source_articles, key=lambda a: len(a.get("clean_text", "")), default=None)
        if richest and len(richest.get("title", "")) > 25 and _is_mostly_latin(richest.get("title", "")):
            body.append(_TITLE_ATTRIBUTION.sub("", richest["title"]).strip())

    if source_names:
        outlet_str = ", ".join(source_names[:5])
        if len(source_names) > 5:
            outlet_str += f" and {len(source_names) - 5} others"
        body.append(
            f"Signal reviewed {source_count} articles from {outlet_str}, "
            "cross-referencing claims for overlap."
        )

    for text in good_supported[1:5]:
        body.append(text)

    prose = _prose_paragraphs(source_articles, prompt_kw)
    if good_supported:
        if prose:
            body.append("Additional details reported by individual sources, pending corroboration:")
            body.extend(prose[:3])
    else:
        body.extend(prose)

    n_uncertain = sum(1 for c in unique_claims if c.get("status") == "uncertain")
    if n_uncertain:
        body.append(
            f"Signal set aside {n_uncertain} additional claim"
            f"{'s' if n_uncertain != 1 else ''} that could not be confirmed "
            "from public sources."
        )

    return [p for p in body if p.strip()], None


def _facts_from_consensus(
    source_articles: list[dict],
    supported: list[dict],
    unique_claims: list[dict],
) -> list[dict]:
    source_names = sorted({str(a["source_name"]) for a in source_articles})
    facts = []

    for claim in supported[:3]:
        sources = claim.get("sources", source_names[:2])
        facts.append({
            "text": claim["claim_text"].rstrip("."),
            "source": "; ".join(sources),
        })

    if not facts:
        good = _good_claim_texts(unique_claims, min_len=30)[:2]
        for text in good:
            facts.append({"text": text.rstrip("."), "source": source_names[0] if source_names else "public source"})

    facts.append({
        "text": f"{len(source_articles)} article candidates reviewed",
        "source": "; ".join(source_names[:6]) or "GDELT public index",
    })
    return facts


def _consensus_level(consensus: list[dict], source_articles: list[dict]) -> str:
    supported = [c for c in consensus if c.get("status") == "supported"]
    conflicting = [c for c in consensus if c.get("status") == "conflicting"]
    domains = {
        domain_from_url(a.get("url", "")) or str(a.get("domain", ""))
        for a in source_articles
        if a.get("url") or a.get("domain")
    }
    if conflicting:
        return "conflicting"
    if len(supported) >= 2 and len(domains) >= 3:
        return "strong"
    if supported:
        return "moderate"
    if source_articles:
        return "limited"
    return "none"


def _quality_scores(source_quality: dict, consensus: list[dict], source_count: int) -> tuple[int, int]:
    """Legacy UI scores are heuristic confidence indicators, not audited truth scores."""
    supported = sum(1 for c in consensus if c.get("status") == "supported")
    domain_count = int(source_quality.get("domain_count", 0) or 0)
    usable = int(source_quality.get("usable_source_count", 0) or 0)
    balance_score = min(98, 62 + domain_count * 7 + min(source_count, 8) * 2)
    verification_score = min(97, 58 + supported * 9 + usable * 3)
    return balance_score, verification_score


def _article_from_consensus(
    prompt: str,
    source_articles: list[dict],
    consensus: list[dict],
    use_gemini: bool = True,
    *,
    generation_mode: str = "thorough",
    source_quality: dict | None = None,
    used_live_sources: bool = True,
    fallback_reason: str | None = None,
    require_gemini: bool = False,
    build_id: str | None = None,
) -> dict:
    supported = [c for c in consensus if c["status"] == "supported"]
    unique = [c for c in consensus if c["status"] in ("unique", "uncertain")]
    source_names = sorted({str(a["source_name"]) for a in source_articles})
    source_count = len(source_articles)
    # "rejected" = claims filtered out as boilerplate/low-quality during synthesis
    rejected = len([c for c in consensus if not _is_good_claim(c.get("claim_text", ""))])

    headline = _best_headline(prompt, supported, source_articles)
    dek = _best_dek(source_count, source_names, supported)
    summary = supported[0]["claim_text"] if supported else (
        headline if headline.endswith("— Signal Coverage") is False
        else f"Signal tracked {source_count} public sources for: {prompt}."
    )
    image_executor = None
    image_future = None
    if getattr(settings, "article_images_enabled", True):
        image_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="article-image")
        image_future = image_executor.submit(
            find_openverse_image,
            prompt,
            timeout=getattr(settings, "article_image_search_timeout_seconds", 4.0),
        )
    try:
        body, gemini_header = _article_body(
            prompt,
            source_articles,
            supported,
            unique,
            use_gemini=use_gemini or require_gemini,
            require_gemini=require_gemini,
            generation_mode=generation_mode,
            build_id=build_id,
        )
    except Exception:
        if image_future:
            image_future.cancel()
        if image_executor:
            image_executor.shutdown(wait=False, cancel_futures=True)
        raise

    image: dict = {}
    if image_future:
        try:
            image = image_future.result(
                timeout=max(0.0, getattr(settings, "article_image_wait_seconds", 1.0))
            ) or {}
        except TimeoutError:
            logger.info("Article image lookup still pending; publishing without an image", extra={"build_id": build_id})
        except Exception:
            logger.exception("Article image lookup failed", extra={"build_id": build_id})
        finally:
            image_executor.shutdown(wait=False, cancel_futures=True)
    if gemini_header:
        headline = gemini_header["headline"]
        dek = gemini_header["dek"]
        if not supported:
            summary = dek or headline
    facts = _facts_from_consensus(source_articles, supported, unique)
    terms = list(dict.fromkeys(re.findall(r"[a-z]{4,}", prompt.lower())))[:5]
    source_quality = source_quality or evaluate_source_quality(source_articles, prompt, gate=THOROUGH_SOURCE_GATE)
    fairness_score, accuracy_score = _quality_scores(source_quality, consensus, source_count)
    consensus_level = _consensus_level(consensus, source_articles)

    return {
        "id": f"write-{int(datetime.now(tz=timezone.utc).timestamp() * 1000)}",
        "source": "Signal desk",
        "tag": "prompt",
        "trendUrl": "",
        "prompt": prompt,
        "headline": headline,
        "dek": dek,
        "summary": summary,
        "body": body,
        "facts": facts,
        "terms": terms,
        "createdAt": datetime.now(tz=timezone.utc).isoformat(),
        "sourceCount": source_count,
        "deniedForBias": rejected,
        "fairnessScore": fairness_score,
        "accuracyScore": accuracy_score,
        "scoreMetadata": {
            "fairnessScore": "Heuristic source-balance score based on outlet/domain diversity; not an audited bias rating.",
            "accuracyScore": "Heuristic verification-confidence score based on usable sources and claim overlap; not a factuality audit.",
        },
        "sources": source_names,
        "sourceLinks": [
            {"source": a["source_name"], "title": a["title"], "url": a["url"]}
            for a in source_articles
            if a.get("url") and a.get("title") and _is_mostly_latin(a.get("title", ""))
        ],
        "image": image,
        "consensus": consensus,
        "generation_mode": generation_mode,
        "source_quality": source_quality,
        "consensus_level": consensus_level,
        "used_live_sources": used_live_sources,
        **({"fallback_reason": fallback_reason} if fallback_reason else {}),
    }


# ── Main entry point ───────────────────────────────────────────────────────────

def _merge_candidates(primary: list[dict], secondary: list[dict], limit: int, prompt: str = "") -> list[dict]:
    candidates = [
        c for c in primary + secondary
        if _is_mostly_latin(c.get("title", "")) and not is_blocked_domain(c.get("url", ""))
    ]
    ranked, _meta = rank_sources(
        candidates,
        prompt,
        limit=limit,
        min_text_chars=20,
        min_relevance=0.10,
        allow_fallback=True,
    )
    return ranked


def _fast_consensus_from_sources(prompt: str, candidates: list[dict]) -> list[dict]:
    pseudo_claims: list[dict] = []
    for index, article in enumerate(candidates):
        text = ". ".join(
            part.strip()
            for part in [
                article.get("title", ""),
                article.get("description", ""),
                article.get("raw_text", "")[:500],
            ]
            if part and str(part).strip()
        )
        claims = extract_claims(text, entities=[], max_claims=2)
        if not claims and article.get("title"):
            claims = [{
                "text": str(article["title"]).rstrip(".") + ".",
                "claim_type": "event",
                "entities": [],
                "confidence_score": 0.62,
            }]
        for claim in claims:
            pseudo_claims.append({
                "claim_text": claim["text"],
                "source_name": article.get("source_name") or f"source-{index}",
                "url": article.get("url", ""),
                "source_domain": domain_from_url(article.get("url", "")) or article.get("domain", ""),
                "confidence_score": claim.get("confidence_score", 0.65),
            })
    return detect_consensus(pseudo_claims, use_semantic=False)


def _fast_article_from_prompt(prompt: str, limit: int = 8, use_gemini: bool = True, build_id: str | None = None) -> dict:
    build_id = build_id or f"build-{uuid.uuid4().hex}"
    fast_limit = max(4, min(limit, 12))
    min_cache = max(2, min(settings.fast_cache_min_sources, fast_limit))
    _set_progress(
        build_id,
        active=True, prompt=prompt,
        stage="fetching",
        stage_label="Scanning today's desk cache...",
        sources_found=0, sources_enriched=0, claims_extracted=0,
        draft_text="", draft_headline="", article=None, error=None,
        started_at=time.time(),
    )

    # 1) Prefer freshly ingested desk coverage first.
    cached: list[dict] = []
    try:
        cached = _cached_articles_for_prompt(prompt, fast_limit)
    except Exception:
        logger.exception("Cached article lookup failed during fast article generation", extra={"build_id": build_id, "prompt": prompt})
        cached = []

    candidates = _merge_candidates(cached, [], fast_limit, prompt)
    used_live_sources = False

    # 2) Only hit live providers when the daily cache is thin.
    if len(candidates) < min_cache:
        _set_progress(
            build_id,
            stage="fetching",
            stage_label="Cache thin — racing Bing, Guardian, and GDELT...",
            sources_found=len(candidates),
        )
        rss_candidates: list[dict] = []
        gdelt_candidates: list[dict] = []
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            futures = {
                pool.submit(fetch_articles_for_query_fast, prompt, fast_limit, min_cache, 5.0): "rss",
                pool.submit(fetch_gdelt_articles, prompt, fast_limit, 0.15): "gdelt",
            }
            try:
                for future in as_completed(futures, timeout=6):
                    try:
                        if futures[future] == "rss":
                            rss_candidates = future.result() or []
                        else:
                            gdelt_candidates = future.result() or []
                    except Exception:
                        logger.exception(
                            "Fast article source fetch failed",
                            extra={"source": futures[future], "build_id": build_id},
                        )
                    merged_live = _merge_candidates(candidates, rss_candidates + gdelt_candidates, fast_limit, prompt)
                    if len(merged_live) >= min_cache:
                        candidates = merged_live
                        used_live_sources = bool(rss_candidates or gdelt_candidates)
                        break
            except TimeoutError:
                logger.warning("Fast article source fetch timed out", extra={"build_id": build_id, "prompt": prompt})
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        candidates = _merge_candidates(candidates, rss_candidates + gdelt_candidates, fast_limit, prompt)
        used_live_sources = used_live_sources or bool(rss_candidates or gdelt_candidates)
    else:
        _set_progress(
            build_id,
            stage="fetching",
            stage_label=f"Using {len(candidates)} fresh desk sources...",
            sources_found=len(candidates),
        )

    if not candidates:
        _set_progress(build_id, active=False, stage="error", stage_label="No sources found", error="No accessible sources were found for a Gemini draft")
        raise GeminiArticleUnavailable("No accessible sources were found for a Gemini draft")

    candidates.sort(key=lambda a: len(a.get("raw_text", "") or a.get("description", "")), reverse=True)
    for candidate in candidates:
        if not candidate.get("raw_text") and candidate.get("description"):
            candidate["raw_text"] = candidate["description"]

    _set_progress(
        build_id,
        stage="writing",
        stage_label=f"Fast draft: Gemini writing from {len(candidates)} sources...",
        sources_found=len(candidates),
        sources_enriched=sum(1 for c in candidates if len(c.get("raw_text", "")) > 120),
    )

    consensus = _fast_consensus_from_sources(prompt, candidates)
    source_quality = evaluate_source_quality(candidates, prompt, gate=SourceGate(min_sources=2, min_domains=2, min_text_chars=80))
    article = _article_from_consensus(
        prompt,
        candidates,
        consensus,
        use_gemini=True,
        generation_mode="fast",
        source_quality=source_quality,
        used_live_sources=used_live_sources,
        require_gemini=True,
        build_id=build_id,
    )
    article["buildId"] = build_id
    article["tag"] = "fast-draft"
    article["summary"] = article["summary"].replace("Signal tracked", "Fast draft from")
    queries.save_generated_article(article)
    _set_progress(
        build_id,
        active=False,
        stage="done",
        stage_label="Done",
        article=article,
        draft_text="",
        draft_headline="",
        error=None,
    )
    return article


def write_article_from_prompt(prompt: str, limit: int = 50, use_gemini: bool = True, mode: str = "thorough", build_id: str | None = None) -> dict:
    """
    Full pipeline for a user-submitted prompt.

    Thorough mode is cache-first and latency-bounded:
    1. Prefer recent desk coverage from Postgres.
    2. Live-fetch only when the cache is thin (Bing/Guardian/GDELT race + capped enrich).
    3. Process a small top-N set of articles, Jaccard consensus, Gemini package write.
    """
    build_id = build_id or f"build-{uuid.uuid4().hex}"
    use_gemini = True
    if mode == "fast":
        return _fast_article_from_prompt(prompt, limit=limit, use_gemini=use_gemini, build_id=build_id)

    thorough_limit = max(4, min(limit, settings.thorough_max_candidates))
    min_cache = max(3, min(settings.thorough_cache_min_sources, thorough_limit))
    _set_progress(
        build_id,
        active=True, prompt=prompt,
        stage="fetching",
        stage_label="Scanning desk cache for thorough coverage...",
        sources_found=0, sources_enriched=0, claims_extracted=0,
        draft_text="", draft_headline="", article=None, error=None,
        started_at=time.time(),
    )

    # 1) Cache first — same daily desk coverage Fast uses.
    cached: list[dict] = []
    try:
        cached = _cached_articles_for_prompt(prompt, thorough_limit)
    except Exception:
        logger.exception("Cached article lookup failed during thorough generation", extra={"build_id": build_id, "prompt": prompt})
        cached = []

    live_candidates = _merge_candidates(cached, [], thorough_limit, prompt)
    used_live_sources = False
    rss_candidates: list[dict] = []
    gdelt_candidates: list[dict] = []

    # 2) Live race only when cache is thin — same early-exit race Fast uses,
    # then a capped enrich pass for the thinnest candidates.
    if len(live_candidates) < min_cache:
        _set_progress(
            build_id,
            stage="fetching",
            stage_label="Racing Bing, Guardian, and GDELT for deeper coverage...",
            sources_found=len(live_candidates),
        )
        pool = ThreadPoolExecutor(max_workers=2)
        try:
            futures = {
                pool.submit(fetch_articles_for_query_fast, prompt, thorough_limit, min_cache, 6.0): "rss",
                pool.submit(fetch_gdelt_articles, prompt, thorough_limit, 0.15): "gdelt",
            }
            try:
                for future in as_completed(futures, timeout=8):
                    try:
                        if futures[future] == "rss":
                            rss_candidates = future.result() or []
                        else:
                            gdelt_candidates = future.result() or []
                    except Exception:
                        logger.exception(
                            "Thorough article source fetch failed",
                            extra={"source": futures[future], "build_id": build_id, "prompt": prompt},
                        )
                    merged_live = _merge_candidates(
                        live_candidates, rss_candidates + gdelt_candidates, thorough_limit, prompt
                    )
                    if len(merged_live) >= min_cache:
                        live_candidates = merged_live
                        used_live_sources = bool(rss_candidates or gdelt_candidates)
                        break
            except TimeoutError:
                logger.warning("Thorough article source fetch timed out", extra={"build_id": build_id, "prompt": prompt})
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        live_candidates = _merge_candidates(live_candidates, rss_candidates + gdelt_candidates, thorough_limit, prompt)
        used_live_sources = used_live_sources or bool(rss_candidates or gdelt_candidates)

        thin = [
            c for c in live_candidates
            if len(c.get("raw_text") or c.get("description") or "") < 300
        ][: max(2, settings.thorough_enrich_limit)]
        if thin:
            _set_progress(
                build_id,
                stage="enriching",
                stage_label=f"Reading full text from {len(thin)} sources...",
                sources_found=len(live_candidates),
            )
            enrich_timeout = max(3, int(settings.thorough_enrich_timeout_seconds))
            enriched_by_url = {}
            with ThreadPoolExecutor(max_workers=min(4, len(thin))) as enrich_pool:
                future_map = {
                    enrich_pool.submit(_enrich_candidate, c): c.get("url", "")
                    for c in thin
                }
                try:
                    for future in as_completed(future_map, timeout=enrich_timeout + 1):
                        url = future_map[future]
                        try:
                            enriched_by_url[url] = future.result(timeout=enrich_timeout)
                        except Exception:
                            continue
                except TimeoutError:
                    logger.warning("Thorough enrich timed out", extra={"build_id": build_id})
            if enriched_by_url:
                live_candidates = [
                    enriched_by_url.get(c.get("url", ""), c) for c in live_candidates
                ]

    all_candidates, ranked_source_meta = rank_sources(
        live_candidates,
        prompt,
        limit=thorough_limit,
        min_text_chars=80,
        min_relevance=0.12,
        allow_fallback=True,
    )

    if not all_candidates:
        _set_progress(build_id, active=False, stage="error", stage_label="No sources found", error="No accessible sources were found for a Gemini draft")
        raise GeminiArticleUnavailable("No accessible sources were found for a Gemini draft")

    source_quality = evaluate_source_quality(all_candidates, prompt, gate=THOROUGH_SOURCE_GATE)
    source_quality["ranking"] = ranked_source_meta
    with_text = [
        c for c in all_candidates
        if max(len(c.get("clean_text", "") or ""), len(c.get("raw_text", "") or "")) >= THOROUGH_SOURCE_GATE.min_text_chars
    ]
    if source_quality["failed_gates"] and len(with_text) < 3:
        _set_progress(build_id, active=False, stage="error", stage_label="Too few sources found", error="Source coverage did not meet the quality gate for a Gemini article")
        raise GeminiArticleUnavailable("Source coverage did not meet the quality gate for a Gemini article")

    # Keep processing bounded — richest text first.
    all_candidates = sorted(
        all_candidates,
        key=lambda a: max(len(a.get("clean_text", "") or ""), len(a.get("raw_text", "") or "")),
        reverse=True,
    )[:thorough_limit]

    _set_progress(
        build_id,
        stage="processing",
        stage_label=f"Extracting claims from {len(all_candidates)} ranked sources…",
        sources_enriched=len(with_text),
        sources_found=len(all_candidates),
    )

    processed = _parallel_process(all_candidates)
    if not processed:
        ids = [queries.insert_article(c) for c in all_candidates if c.get("raw_text")]
        processed = [queries.get_article(i) for i in ids if i]
        processed = [a for a in processed if a]

    if not processed:
        _set_progress(build_id, active=False, stage="error", stage_label="Processing failed", error="Source processing failed before Gemini could write an article")
        raise GeminiArticleUnavailable("Source processing failed before Gemini could write an article")

    cluster_id = queries.create_cluster(prompt, [int(a["id"]) for a in processed])
    cluster_claims = queries.get_cluster_claims(cluster_id)

    _set_progress(
        build_id,
        stage="consensus",
        stage_label=f"Comparing claims across {len(processed)} articles…",
        claims_extracted=len(cluster_claims),
    )

    # Jaccard-only consensus avoids embedding model load time on the request path.
    consensus = detect_consensus(cluster_claims, use_semantic=False)
    supported = [c for c in consensus if c["status"] == "supported"]

    _set_progress(
        build_id,
        stage="writing",
        stage_label=f"Found {len(supported)} corroborated claims — Gemini synthesizing article…",
    )

    queries.replace_consensus_claims(cluster_id, consensus)
    article = _article_from_consensus(
        prompt,
        processed,
        consensus,
        use_gemini=use_gemini,
        generation_mode="thorough",
        source_quality=source_quality,
        used_live_sources=used_live_sources,
        require_gemini=True,
        build_id=build_id,
    )
    article["buildId"] = build_id
    queries.save_generated_article(article)

    _set_progress(
        build_id,
        active=False,
        stage="done",
        stage_label="Done",
        article=article,
        draft_text="",
        draft_headline="",
        error=None,
    )
    return article
