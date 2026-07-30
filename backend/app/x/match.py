from __future__ import annotations

"""Match pasted X post URLs to already-written Signal articles."""

import re
from datetime import datetime, timezone
from typing import Any

from app.db import queries
from app.x.client import get_x_client, status_id_from_url
from app.x.reply import article_public_url, share_intent_url, x_reply_text
from app.nlp.ner import extract_entities

_URL_RE = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x\.com|twitter\.com)/[^\s]+/status/\d+[^\s]*",
    re.I,
)
_BARE_STATUS_RE = re.compile(r"(?:^|[\s,;])(?:status/)?(\d{8,})(?:$|[\s,;])")


def extract_x_urls(raw: str) -> list[str]:
    """Pull unique x.com/twitter.com status URLs (or bare status ids) from pasted text."""
    text = str(raw or "")
    found: list[str] = []
    seen: set[str] = set()

    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(").,]\"'")
        post_id = status_id_from_url(url)
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)
        found.append(url if url.startswith("http") else f"https://x.com/i/web/status/{post_id}")

    for match in _BARE_STATUS_RE.finditer(text):
        post_id = match.group(1)
        if post_id in seen:
            continue
        # Skip ids that already appeared inside a full URL capture.
        if any(post_id in item for item in found):
            continue
        seen.add(post_id)
        found.append(f"https://x.com/i/web/status/{post_id}")

    return found


def _article_catalog(articles: list[dict[str, Any]]) -> list[dict[str, str]]:
    catalog: list[dict[str, str]] = []
    for article in articles:
        article_id = str(article.get("id") or "").strip()
        headline = str(article.get("headline") or "").strip()
        if not article_id or not headline:
            continue
        body = article.get("body") or []
        if isinstance(body, list):
            body_preview = " ".join(str(part) for part in body[:2] if part)
        else:
            body_preview = str(body)
        catalog.append(
            {
                "id": article_id,
                "headline": headline,
                "dek": str(article.get("dek") or "").strip()[:240],
                "section": str(article.get("section") or "latest"),
                "preview": body_preview[:280],
                "source": str(article.get("source") or ""),
                "createdAt": str(article.get("createdAt") or ""),
            }
        )
    return catalog


def _keyword_score(left: str, right: str) -> float:
    left_words = {
        word
        for word in re.findall(r"[a-z0-9]{3,}", (left or "").lower())
        if word not in {"the", "and", "for", "with", "from", "that", "this", "https", "http", "www"}
    }
    right_words = {
        word
        for word in re.findall(r"[a-z0-9]{3,}", (right or "").lower())
        if word not in {"the", "and", "for", "with", "from", "that", "this", "https", "http", "www"}
    }
    if not left_words or not right_words:
        return 0.0
    overlap = left_words & right_words
    return len(overlap) / max(1, min(len(left_words), len(right_words)))


def _fallback_matches(
    posts: list[dict[str, Any]],
    articles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    catalog = _article_catalog(articles)
    used: set[str] = set()
    matches: list[dict[str, Any]] = []
    for post in posts:
        post_text = " ".join(part for part in [post.get("text") or "", post.get("topic") or ""] if part)
        post_entities = {
            str(entity.get("text") or "").strip().lower()
            for entity in extract_entities(post_text)
            if str(entity.get("type") or "").upper() in {"PERSON", "ORG", "GPE", "EVENT", "PRODUCT"}
        }
        author = str(post.get("author") or "").strip().lstrip("@").lower()
        best = None
        best_score = 0.0
        for item in catalog:
            if item["id"] in used:
                continue
            headline_score = _keyword_score(post_text, item["headline"])
            supporting_score = _keyword_score(post_text, f"{item['dek']} {item['preview']}")
            article_entities = {
                str(entity.get("text") or "").strip().lower()
                for entity in extract_entities(f"{item['headline']} {item['dek']}")
                if str(entity.get("type") or "").upper() in {"PERSON", "ORG", "GPE", "EVENT", "PRODUCT"}
            }
            entity_overlap = len(post_entities & article_entities)
            exact_entity_bonus = 0.24 if entity_overlap else 0.0
            if entity_overlap >= 2:
                exact_entity_bonus += 0.14
            author_bonus = 0.0
            if author and author in f"{item['headline']} {item['dek']} {item['source']}".lower():
                author_bonus = 0.12
            recency_bonus = 0.0
            try:
                created = datetime.fromisoformat(item["createdAt"].replace("Z", "+00:00"))
                age_hours = max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 3600)
                recency_bonus = max(0.0, 0.12 * (1.0 - age_hours / 168.0))
            except (TypeError, ValueError):
                pass
            score = (
                headline_score * 0.58
                + supporting_score * 0.22
                + exact_entity_bonus
                + author_bonus
                + recency_bonus
            )
            if score > best_score:
                best_score = score
                best = item
        if best and best_score >= 0.18:
            used.add(best["id"])
            matches.append(
                {
                    "postId": post["postId"],
                    "articleId": best["id"],
                    "confidence": round(min(0.85, best_score + 0.2), 2),
                    "reason": "deterministic headline, entity, author, and recency score",
                }
            )
        else:
            matches.append(
                {
                    "postId": post["postId"],
                    "articleId": "",
                    "confidence": 0.0,
                    "reason": "no confident article match",
                }
            )
    return matches


def match_x_urls_to_articles(
    raw_urls: str,
    *,
    hours: int = 72,
    article_limit: int = 80,
) -> dict[str, Any]:
    """
    Resolve pasted X URLs, load recent ready articles, and match deterministically.

    Returns rows ready for the admin terminal to view / reply / post.
    """
    urls = extract_x_urls(raw_urls)
    if not urls:
        return {"count": 0, "matched": 0, "rows": [], "source": "none", "error": "No X post URLs found"}

    client = get_x_client()
    posts: list[dict[str, Any]] = []
    for url in urls[:40]:
        post_id = status_id_from_url(url)
        if not post_id:
            continue
        candidate = None
        lookup_error = ""
        try:
            candidate = client.lookup_post(post_id)
        except Exception as exc:
            lookup_error = str(exc) or type(exc).__name__
        text = ""
        author = ""
        topic = ""
        if candidate:
            text = (candidate.snippet or candidate.prompt or candidate.topic or "").strip()
            author = candidate.author_handle or ""
            topic = candidate.topic or ""
            url = candidate.trend_url or url
        posts.append(
            {
                "url": url,
                "postId": post_id,
                "text": text,
                "topic": topic,
                "author": author,
                "lookupError": lookup_error,
            }
        )

    articles = queries.list_recent_x_feed_articles(hours=hours, limit=article_limit)
    catalog = _article_catalog(articles)
    article_by_id = {str(article.get("id")): article for article in articles}

    source = "deterministic"
    raw_matches = _fallback_matches(posts, articles)

    match_by_post = {str(item.get("postId") or ""): item for item in raw_matches}
    rows: list[dict[str, Any]] = []
    matched = 0
    for post in posts:
        choice = match_by_post.get(post["postId"]) or {}
        article_id = str(choice.get("articleId") or "").strip()
        article = article_by_id.get(article_id) if article_id else None
        row: dict[str, Any] = {
            "url": post["url"],
            "postId": post["postId"],
            "postText": post.get("text") or "",
            "author": post.get("author") or "",
            "lookupError": post.get("lookupError") or "",
            "articleId": "",
            "headline": "",
            "section": "",
            "articleUrl": "",
            "replyText": "",
            "intentUrl": "",
            "confidence": float(choice.get("confidence") or 0),
            "reason": str(choice.get("reason") or ""),
            "status": "unmatched",
        }
        if article:
            public_url = article_public_url(str(article["id"]))
            reply = x_reply_text(article, public_url)
            row.update(
                {
                    "articleId": article["id"],
                    "headline": article.get("headline") or "",
                    "section": article.get("section") or "latest",
                    "articleUrl": public_url,
                    "replyText": reply,
                    "intentUrl": share_intent_url(
                        public_url,
                        article.get("headline") or "",
                        reply_text=reply,
                        in_reply_to_id=post["postId"],
                    ),
                    "status": "matched",
                    "xShare": article.get("xShare") or {},
                }
            )
            matched += 1
        elif not row["reason"]:
            row["reason"] = "no matching ready article"
        rows.append(row)

    return {
        "count": len(rows),
        "matched": matched,
        "rows": rows,
        "source": source,
        "articleCount": len(catalog),
    }
