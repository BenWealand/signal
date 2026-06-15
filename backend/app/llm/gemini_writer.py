from __future__ import annotations

import collections
import json
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app.config import settings

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Per-article token budget: keep prompt under ~6 000 chars of source material
# so Gemini can respond within the free-tier latency window.
_MAX_SOURCE_CHARS = 9_000
_MAX_PER_ARTICLE  = 1_300   # chars per source article fed to Gemini

# ── Rate limiter ───────────────────────────────────────────────────────────────
# Free tier: 15 RPM. We cap at 10/min locally to leave headroom, AND track
# the last 429 timestamp — if Google rejected us recently we back off for
# 65 s so the server-side window definitely resets before we retry.
_RATE_LIMIT        = 10        # max local calls per window
_RATE_WINDOW       = 60.0      # rolling window in seconds
_COOLDOWN_AFTER_429 = 65.0     # seconds to wait after a Google-side 429

_rate_lock    = threading.Lock()
_call_times: collections.deque[float] = collections.deque()
_last_429_at: float = 0.0      # monotonic timestamp of most recent 429
_last_error_lock = threading.Lock()
_last_error: dict[str, object] | None = None


def _set_last_error(**error: object) -> None:
    global _last_error
    with _last_error_lock:
        _last_error = {
            **error,
            "timestamp": time.time(),
        }


def _clear_last_error() -> None:
    global _last_error
    with _last_error_lock:
        _last_error = None


def get_last_gemini_error() -> dict[str, object] | None:
    with _last_error_lock:
        return dict(_last_error) if _last_error else None


def _rate_limited() -> bool:
    """
    Return True (and skip the call) if:
      - We're still in the 65-second cooldown after a Google 429, OR
      - We've already sent 10 calls in the current 60-second window.
    Records the call time when we decide to allow it.
    """
    now = time.monotonic()
    with _rate_lock:
        # Respect the server-side cooldown window after a 429
        if now - _last_429_at < _COOLDOWN_AFTER_429:
            remaining = int(_COOLDOWN_AFTER_429 - (now - _last_429_at))
            print(f"[Gemini] In 429 cooldown — {remaining}s remaining.", file=sys.stderr)
            return True

        # Drop timestamps outside the rolling window
        while _call_times and now - _call_times[0] > _RATE_WINDOW:
            _call_times.popleft()
        if len(_call_times) >= _RATE_LIMIT:
            return True
        _call_times.append(now)
        return False


def _record_429() -> None:
    global _last_429_at
    with _rate_lock:
        _last_429_at = time.monotonic()


def _build_source_block(articles: list[dict]) -> tuple[str, int]:
    """
    Select the richest articles (most body text) and format them for the
    Gemini prompt.  Returns (formatted_block, article_count_used).
    """
    ordered = sorted(
        articles,
        key=lambda a: len(a.get("clean_text", "") or a.get("raw_text", "")),
        reverse=True,
    )

    blocks: list[str] = []
    total = 0
    for art in ordered:
        source = (art.get("source_name") or "Unknown").strip()
        title  = (art.get("title")       or "").strip()
        body   = (art.get("clean_text")  or art.get("raw_text") or "").strip()

        # Skip non-Latin or empty
        if not title and not body:
            continue

        text = body[:_MAX_PER_ARTICLE] if body else ""
        block = f"[{source}]\nTitle: {title}\n{text}".strip()
        blocks.append(block)
        total += len(block)
        if total >= _MAX_SOURCE_CHARS:
            break

    return "\n---\n".join(blocks), len(blocks)


def write_article_with_gemini(
    query: str,
    source_articles: list[dict],
) -> str | None:
    """
    Call Gemini to synthesize a polished 6-8 paragraph news article from
    collected source material.

    Returns the article body as plain text (paragraphs separated by blank
    lines), or None if Gemini is unavailable or the call fails.

    Quota: 1 API call per article generation.
    Free tier: Gemini 2.0 Flash — 1 500 req/day, 15 RPM.
    """
    key = settings.gemini_api_key
    if not key:
        _set_last_error(kind="config", message="GEMINI_API_KEY is not set")
        return None

    if _rate_limited():
        _set_last_error(kind="rate_limit", message="Local Gemini rate cap reached")
        print("[Gemini] Local rate cap reached — skipping to preserve quota.", file=sys.stderr)
        return None

    source_block, n_sources = _build_source_block(source_articles)
    if not source_block:
        _set_last_error(kind="input", message="No source material was available for Gemini")
        return None

    model = settings.gemini_model  # default "gemini-2.0-flash"
    _clear_last_error()

    prompt = f"""You are a journalist at Signal, a news-transparency platform that shows readers how multiple outlets cover the same story.

Topic: {query}

SOURCE MATERIAL ({n_sources} sources):
---
{source_block}
---

Write a factual news article based ONLY on the source material above. Follow these rules exactly:

1. 6-8 substantive paragraphs, Associated Press style, plain prose only.
2. Lead paragraph: the single most important confirmed fact.
3. Middle paragraphs: include the concrete details available in the sources: agencies, places, people, numbers, timing, policy terms, company names, and source-specific caveats when present.
4. Attribute key details to specific outlets ("AP reported that...", "According to The Guardian,..."). Where 2+ sources confirm the same fact, state it as established. Where only 1 source reports something, attribute it.
5. Final paragraph: meaningful context or background, not a generic wrap-up.
6. Do NOT invent any fact, quote, statistic, or name not present in the source material above.
7. Do NOT include a headline, byline, or dateline — only the body paragraphs.
8. Write in plain prose. No bullet points, no headers, no markdown.
9. Correct all grammar and spelling. Write at a professional newspaper standard."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 1536,
            "topP": 0.9,
        },
    }).encode("utf-8")

    url = f"{_API_BASE}/{urllib.parse.quote(model, safe='')}:generateContent"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)

        if "error" in data:
            _set_last_error(kind="api", model=model, error=data["error"])
            print(f"[Gemini] API error: {data['error']}", file=sys.stderr)
            return None

        candidates = data.get("candidates", [])
        if not candidates:
            _set_last_error(kind="response", model=model, message="Gemini returned no candidates")
            return None
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            _set_last_error(kind="response", model=model, message="Gemini returned no content parts")
            return None
        text = parts[0].get("text", "").strip()
        if len(text) <= 100:
            _set_last_error(kind="response", model=model, message="Gemini returned too little text")
            return None
        return text

    except urllib.error.HTTPError as exc:
        body: dict[str, object] = {}
        try:
            body = json.loads(exc.read().decode("utf-8", errors="ignore"))
        except Exception:
            body = {}
        details = body.get("error", {}) if isinstance(body, dict) else {}
        reason = None
        if isinstance(details, dict):
            for item in details.get("details") or []:
                if isinstance(item, dict) and item.get("reason"):
                    reason = item.get("reason")
                    break
        message = details.get("message", str(exc)) if isinstance(details, dict) else str(exc)
        status = details.get("status") if isinstance(details, dict) else None
        _set_last_error(
            kind="http",
            model=model,
            http_status=exc.code,
            api_status=status,
            reason=reason,
            message=message,
        )
        if exc.code == 429:
            print(f"[Gemini] 429 detail — status: {status}, message: {str(message)[:200]}", file=sys.stderr)
            # Try fallback model before giving up
            fallback_model = "gemini-1.5-flash-latest"
            if model != fallback_model:
                print(f"[Gemini] Trying fallback model {fallback_model}…", file=sys.stderr)
                fallback_url = f"{_API_BASE}/{urllib.parse.quote(fallback_model, safe='')}:generateContent"
                fallback_req = urllib.request.Request(
                    fallback_url, data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "x-goog-api-key": key,
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(fallback_req, timeout=30) as resp:
                        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                    text = parts[0].get("text", "").strip() if parts else ""
                    if len(text) > 100:
                        print(f"[Gemini] Fallback to {fallback_model} succeeded.", file=sys.stderr)
                        _set_last_error(kind="fallback", model=fallback_model, original_model=model, original_http_status=exc.code)
                        return text
                except Exception as fe:
                    print(f"[Gemini] Fallback also failed: {fe}", file=sys.stderr)
            _record_429()
            print("[Gemini] 65 s cooldown started. Rule-based fallback active.", file=sys.stderr)
        else:
            print(f"[Gemini] HTTP {exc.code}: {message}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="request", model=model, message=str(exc))
        print(f"[Gemini] Request failed: {exc}", file=sys.stderr)
        return None
