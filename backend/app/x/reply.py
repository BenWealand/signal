from __future__ import annotations

import re

from app.config import settings


def _clean(text: str, max_chars: int = 420) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:max_chars].rstrip()


def build_prompt(candidate_topic: str = "", snippet: str = "", prompt: str = "") -> str:
    """Merge topic/snippet/prompt into a single news query for Gemini."""
    prompt = _clean(prompt, 240)
    topic = _clean(candidate_topic, 120)
    snippet = _clean(snippet, 280)
    parts: list[str] = []
    if prompt:
        parts.append(prompt)
    if topic and topic.lower() not in prompt.lower():
        parts.append(f"Trending topic: {topic}")
    if snippet and snippet.lower() not in " ".join(parts).lower():
        parts.append(f"Social post snippet: {snippet}")
    combined = ". ".join(parts).strip(". ")
    if not combined:
        raise ValueError("Provide prompt, trending_topic, or snippet")
    return combined


def article_public_url(article_id: str) -> str:
    base = settings.public_article_base_url.strip().rstrip("/")
    query = f"article={article_id}"
    return f"{base}/?{query}" if base else f"/?{query}"


def x_reply_text(article: dict, article_url: str) -> str:
    headline = _clean(article.get("headline", "Signal article"), 180)
    suffix = f"Read the sourced Signal write-up: {article_url}"
    text = f"{headline}\n\n{suffix}"
    if len(text) <= 260:
        return text
    return f"{headline[: max(40, 256 - len(suffix))].rstrip()}...\n\n{suffix}"


def share_intent_url(article_url: str, headline: str = "") -> str:
    """Browser share intent — no X API required."""
    from urllib.parse import quote

    text = _clean(f"{headline} - Signal Dispatch" if headline else "Signal Dispatch", 180)
    return (
        "https://x.com/intent/tweet"
        f"?text={quote(text)}"
        f"&url={quote(article_url)}"
    )
