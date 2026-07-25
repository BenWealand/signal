from __future__ import annotations

"""Craft one Signal article from many pasted X post URLs."""

import logging
import re
import uuid
from typing import Any, Callable

from app.db import queries
from app.policy.prompt_filter import prompt_is_blocked
from app.processing.article_writer import GeminiArticleUnavailable, write_article_from_prompt
from app.x.client import get_x_client, status_id_from_url
from app.x.match import extract_x_urls
from app.x.models import XCandidate
from app.x.reply import article_public_url, share_intent_url, x_reply_text

logger = logging.getLogger(__name__)

MAX_CRAFT_URLS = 12


def _clean_line(text: str, limit: int = 280) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit].rstrip()


def build_multi_link_prompt(posts: list[dict[str, Any]], focus: str = "") -> str:
    """Combine looked-up X posts (+ optional focus) into one article prompt."""
    lines: list[str] = []
    for index, post in enumerate(posts, start=1):
        author = _clean_line(post.get("author") or "", 40)
        text = _clean_line(post.get("text") or post.get("topic") or "", 320)
        if not text and post.get("lookupError"):
            text = f"(post {post.get('postId')}: lookup failed)"
        if not text:
            text = f"X post {post.get('postId')}"
        handle = f"@{author}" if author else "unknown"
        lines.append(f"{index}. {handle}: {text}")

    focus_line = _clean_line(focus, 400)
    parts = [
        "Write a sourced news article covering the shared theme across these public X posts.",
        "Use independent reporting. Do not treat the tweets themselves as cited news sources.",
        "Posts:",
        *lines,
    ]
    if focus_line:
        parts.append(f"Optional focus: {focus_line}")
    return "\n".join(parts)


def _lookup_posts(urls: list[str]) -> list[dict[str, Any]]:
    client = get_x_client()
    posts: list[dict[str, Any]] = []
    for url in urls[:MAX_CRAFT_URLS]:
        post_id = status_id_from_url(url)
        if not post_id:
            continue
        candidate: XCandidate | None = None
        lookup_error = ""
        try:
            candidate = client.lookup_post(post_id)
        except Exception as exc:
            lookup_error = str(exc) or type(exc).__name__
        text = ""
        author = ""
        topic = ""
        resolved_url = url
        if candidate:
            text = (candidate.snippet or candidate.prompt or candidate.topic or "").strip()
            author = candidate.author_handle or ""
            topic = candidate.topic or ""
            resolved_url = candidate.trend_url or url
        posts.append(
            {
                "url": resolved_url,
                "postId": post_id,
                "text": text,
                "topic": topic,
                "author": author,
                "lookupError": lookup_error,
            }
        )
    return posts


def craft_article_from_x_urls(
    raw_urls: str,
    *,
    focus: str = "",
    mode: str = "fast",
    source_limit: int = 10,
    write_fn: Callable[..., dict] | None = None,
) -> dict[str, Any]:
    """
    Paste many X links → write one article → return per-post Open-in-X rows.

    Each row shares the same article draft but sets intentUrl.in_reply_to to that post.
    """
    urls = extract_x_urls(raw_urls)
    if not urls:
        return {
            "status": "empty",
            "error": "No X post URLs found",
            "count": 0,
            "posts": [],
            "articleId": "",
            "articleUrl": "",
            "replyText": "",
            "headline": "",
        }

    posts = _lookup_posts(urls)
    if not posts:
        return {
            "status": "empty",
            "error": "No resolvable X post IDs found",
            "count": 0,
            "posts": [],
            "articleId": "",
            "articleUrl": "",
            "replyText": "",
            "headline": "",
        }

    prompt = build_multi_link_prompt(posts, focus=focus)
    blocked = prompt_is_blocked(prompt)
    if blocked.blocked:
        return {
            "status": "blocked",
            "error": f"prompt_blocked:{blocked.source}",
            "count": len(posts),
            "posts": [],
            "articleId": "",
            "articleUrl": "",
            "replyText": "",
            "headline": "",
        }

    build_id = f"build-{uuid.uuid4().hex}"
    writer = write_fn or write_article_from_prompt
    try:
        article = writer(prompt, limit=source_limit, mode=mode, build_id=build_id)
    except GeminiArticleUnavailable as exc:
        return {
            "status": "error",
            "error": str(exc),
            "count": len(posts),
            "posts": [],
            "articleId": "",
            "articleUrl": "",
            "replyText": "",
            "headline": "",
        }
    except Exception as exc:
        logger.exception("Multi-link X article craft failed")
        return {
            "status": "error",
            "error": str(exc) or "article_write_failed",
            "count": len(posts),
            "posts": [],
            "articleId": "",
            "articleUrl": "",
            "replyText": "",
            "headline": "",
        }

    article["buildId"] = build_id
    article["source"] = "Signal desk"
    article["trendUrl"] = posts[0]["url"]
    article["tag"] = "x-multi"
    article["ownerUserId"] = None
    article["status"] = article.get("status") or "published"
    # Keep the linked post list with the article for later admin views.
    meta = dict(article.get("scoreMetadata") or {})
    meta["linkedXPosts"] = [
        {"postId": post["postId"], "url": post["url"], "author": post.get("author") or ""}
        for post in posts
    ]
    article["scoreMetadata"] = meta
    queries.save_generated_article(article)

    article_url = article_public_url(str(article["id"]))
    reply = x_reply_text(article, article_url)
    headline = str(article.get("headline") or "")
    section = str(article.get("section") or "latest")

    rows: list[dict[str, Any]] = []
    for post in posts:
        ready = bool(post.get("text") or not post.get("lookupError"))
        rows.append(
            {
                "url": post["url"],
                "postId": post["postId"],
                "postText": post.get("text") or "",
                "author": post.get("author") or "",
                "lookupError": post.get("lookupError") or "",
                "articleId": article["id"],
                "headline": headline,
                "section": section,
                "articleUrl": article_url,
                "replyText": reply,
                "intentUrl": share_intent_url(
                    article_url,
                    headline,
                    reply_text=reply,
                    in_reply_to_id=post["postId"],
                ),
                "status": "ready" if ready else "lookup_failed",
                "xShare": {"posted": False},
            }
        )

    return {
        "status": "ok",
        "count": len(rows),
        "ready": sum(1 for row in rows if row["status"] == "ready"),
        "articleId": article["id"],
        "articleUrl": article_url,
        "headline": headline,
        "section": section,
        "sourceCount": article.get("sourceCount") or 0,
        "replyText": reply,
        "intentUrl": share_intent_url(article_url, headline, reply_text=reply),
        "posts": rows,
        "promptPreview": prompt[:500],
    }
