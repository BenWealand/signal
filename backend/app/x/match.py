from __future__ import annotations

"""Match pasted X post URLs to already-written Signal articles."""

import re
from typing import Any

from app.db import queries
from app.x.client import get_x_client, status_id_from_url
from app.x.reply import article_public_url, share_intent_url, x_reply_text

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
        post_text = " ".join(
            part for part in [post.get("text") or "", post.get("topic") or "", post.get("author") or ""] if part
        )
        best = None
        best_score = 0.0
        for item in catalog:
            if item["id"] in used:
                continue
            score = _keyword_score(post_text, f"{item['headline']} {item['dek']} {item['preview']}")
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
                    "reason": "keyword overlap fallback",
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
    Resolve pasted X URLs, load recent ready articles, and match with Gemini.

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

    gemini_matches = None
    source = "fallback"
    if catalog and any(post.get("text") for post in posts):
        try:
            from app.llm.gemini_writer import match_x_posts_to_articles_with_gemini

            gemini_matches = match_x_posts_to_articles_with_gemini(posts, catalog)
        except Exception:
            gemini_matches = None
    if gemini_matches is not None:
        source = "gemini"
        raw_matches = gemini_matches
    else:
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
