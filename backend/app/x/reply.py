from __future__ import annotations

import re

from app.config import settings
from app.x.prompt import search_prompt_from_x_post

# Soft cap before X's 280 hard limit (post_tweet also truncates).
X_POST_SOFT_LIMIT = 275


def _clean(text: str, max_chars: int = 420) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:max_chars].rstrip()


def _paragraphs_from_article(article: dict) -> list[str]:
    """Prefer body paragraphs; fall back to dek/summary as prose lines."""
    body = article.get("body") or []
    paras: list[str] = []
    if isinstance(body, list):
        for item in body:
            cleaned = _clean(str(item or ""), 500)
            if cleaned:
                paras.append(cleaned)
    elif isinstance(body, str) and body.strip():
        for chunk in re.split(r"\n+", body):
            cleaned = _clean(chunk, 500)
            if cleaned:
                paras.append(cleaned)

    if not paras:
        for key in ("dek", "summary"):
            cleaned = _clean(str(article.get(key) or ""), 500)
            if cleaned:
                paras.append(cleaned)
    return paras


def build_prompt(candidate_topic: str = "", snippet: str = "", prompt: str = "") -> str:
    """Merge X context into a deterministic, bounded news-search query."""
    prompt = _clean(prompt, 240)
    topic = _clean(candidate_topic, 120)
    snippet = search_prompt_from_x_post(snippet)
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
    """
    Public SPA share URL: `{PUBLIC_ARTICLE_BASE_URL}/article/{id}`.

    The Vercel `/article/:id` route loads via Supabase PostgREST first
    (see src/lib/articles.js), so shared links stay fast without waiting on Render.
    """
    base = (settings.public_article_base_url or "").strip().rstrip("/")
    path = f"/article/{article_id}"
    return f"{base}{path}" if base else path


def _draft_teaser_lines(article: dict) -> list[str]:
    """
    Build the post teaser: full line 1, full line 2, then ~half of line 3 + ….

    Lines are taken from the article itself (headline, then body/dek/summary).
    """
    headline = _clean(str(article.get("headline") or "Signal article"), 160)
    paras = _paragraphs_from_article(article)

    line2 = ""
    line3_src = ""
    dek = _clean(str(article.get("dek") or ""), 200)
    if dek and dek.lower() != headline.lower():
        line2 = dek
        line3_src = paras[0] if paras else _clean(str(article.get("summary") or ""), 200)
    elif paras:
        line2 = paras[0]
        line3_src = paras[1] if len(paras) > 1 else ""
    else:
        line2 = _clean(str(article.get("summary") or ""), 200)

    lines = [headline]
    if line2 and line2.lower() != headline.lower():
        lines.append(line2)

    line3 = _clean(line3_src, 240)
    if line3 and line3.lower() not in {headline.lower(), (line2 or "").lower()}:
        cut = max(24, len(line3) // 2)
        # Prefer breaking on a word boundary near the midpoint.
        chunk = line3[:cut].rstrip()
        if " " in chunk and cut < len(line3):
            chunk = chunk.rsplit(" ", 1)[0]
        lines.append(f"{chunk.rstrip('.,;:')}…")

    return [line for line in lines if line]


def x_reply_text(article: dict, article_url: str) -> str:
    """
    Promote draft for X:

      {line 1}
      {line 2}
      {half of line 3}…

      {article_url}
    """
    url = (article_url or "").strip()
    teaser = "\n".join(_draft_teaser_lines(article)).strip()
    if not teaser:
        teaser = "Signal Dispatch"

    if url:
        text = f"{teaser}\n\n{url}"
    else:
        text = teaser

    if len(text) <= X_POST_SOFT_LIMIT:
        return text

    # Shrink from the teaser bottom up; always keep the share URL.
    lines = teaser.split("\n")
    while lines and len("\n".join(lines) + (f"\n\n{url}" if url else "")) > X_POST_SOFT_LIMIT:
        last = lines[-1]
        if last.endswith("…") and len(last) > 40:
            lines[-1] = last[: max(28, len(last) - 24)].rstrip(".,;: …") + "…"
        elif len(lines) > 1:
            lines.pop()
        else:
            budget = X_POST_SOFT_LIMIT - (len(url) + 4 if url else 0)
            lines[0] = _clean(lines[0], max(40, budget)) + ("…" if budget < len(lines[0]) else "")
            break

    teaser = "\n".join(lines).strip() or "Signal Dispatch"
    return f"{teaser}\n\n{url}" if url else teaser


def share_intent_url(
    article_url: str,
    headline: str = "",
    reply_text: str = "",
    in_reply_to_id: str = "",
) -> str:
    """Browser share intent — no X API required. Prefers full promote draft when provided."""
    from urllib.parse import quote

    draft = (reply_text or "").strip()
    reply_id = (in_reply_to_id or "").strip()
    if draft:
        # Draft already includes the supabase-fast /article/:id link.
        url = f"https://x.com/intent/tweet?text={quote(draft)}"
        return f"{url}&in_reply_to={quote(reply_id)}" if reply_id else url

    text = _clean(f"{headline} — Signal Dispatch" if headline else "Signal Dispatch", 180)
    url = (article_url or "").strip()
    if url:
        intent = (
            "https://x.com/intent/tweet"
            f"?text={quote(text)}"
            f"&url={quote(url)}"
        )
        return f"{intent}&in_reply_to={quote(reply_id)}" if reply_id else intent
    intent = f"https://x.com/intent/tweet?text={quote(text)}"
    return f"{intent}&in_reply_to={quote(reply_id)}" if reply_id else intent
