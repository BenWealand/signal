from __future__ import annotations

import collections
import json
import re
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
_FAST_MAX_SOURCE_CHARS = 5_500
_FAST_MAX_PER_ARTICLE = 900

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

# Model ids Google has shut down; requests to them fail with HTTP 404.
# Deployments may still pin one of these via GEMINI_MODEL, so remap to the
# maintained "-latest" alias instead of failing every article write.
_RETIRED_MODELS = frozenset({
    "gemini-1.0-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-flash-latest",
    "gemini-1.5-pro",
    "gemini-1.5-pro-latest",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
})
_MODEL_ALIAS_FALLBACK = "gemini-flash-latest"       # always points at the current flash model
_MODEL_LITE_FALLBACK  = "gemini-flash-lite-latest"  # separate quota bucket for 429 retries / fast mode


def _active_model(mode: str = "thorough") -> str:
    if mode == "fast":
        model = (settings.gemini_fast_model or "").strip() or _MODEL_LITE_FALLBACK
    else:
        model = (settings.gemini_model or "").strip() or _MODEL_ALIAS_FALLBACK
    if model in _RETIRED_MODELS:
        print(
            f"[Gemini] Model {model} has been retired by Google - using {_MODEL_ALIAS_FALLBACK} instead.",
            file=sys.stderr,
        )
        return _MODEL_ALIAS_FALLBACK if mode != "fast" else _MODEL_LITE_FALLBACK
    return model


def _source_budgets(mode: str) -> tuple[int, int]:
    if mode == "fast":
        return _FAST_MAX_SOURCE_CHARS, _FAST_MAX_PER_ARTICLE
    return _MAX_SOURCE_CHARS, _MAX_PER_ARTICLE


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


def _build_source_block(articles: list[dict], mode: str = "thorough") -> tuple[str, int]:
    """
    Select the richest articles (most body text) and format them for the
    Gemini prompt.  Returns (formatted_block, article_count_used).
    """
    max_source_chars, max_per_article = _source_budgets(mode)
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

        text = body[:max_per_article] if body else ""
        block = f"[{source}]\nTitle: {title}\n{text}".strip()
        blocks.append(block)
        total += len(block)
        if total >= max_source_chars:
            break

    return "\n---\n".join(blocks), len(blocks)


def _parse_package_text(text: str) -> dict[str, str] | None:
    """Parse the HEADLINE/DEK/BODY package format from a Gemini response."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    # Prefer tagged package format.
    headline_match = re.search(r"<<<HEADLINE>>>\s*(.+)", cleaned)
    dek_match = re.search(r"<<<DEK>>>\s*(.+)", cleaned)
    body_match = re.search(r"<<<BODY>>>\s*([\s\S]+)", cleaned)
    if headline_match and dek_match and body_match:
        headline = headline_match.group(1).strip().strip('"')
        dek = dek_match.group(1).strip().strip('"')
        body = body_match.group(1).strip()
        if len(headline.split()) >= 4 and len(dek.split()) >= 5 and len(body) > 100:
            return {"headline": headline, "dek": dek, "body": body}
    # JSON fallback.
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            headline = str(parsed.get("headline", "")).strip().strip('"')
            dek = str(parsed.get("dek", "")).strip().strip('"')
            body = str(parsed.get("body", "")).strip()
            if len(headline.split()) >= 4 and len(dek.split()) >= 5 and len(body) > 100:
                return {"headline": headline, "dek": dek, "body": body}
    except Exception:
        pass
    # Body-only fallback for legacy callers / partial stream.
    if len(cleaned) > 100 and "<<<HEADLINE>>>" not in cleaned:
        return {"headline": "", "dek": "", "body": cleaned}
    return None


def _package_prompt(query: str, source_block: str, n_sources: int, mode: str) -> str:
    paragraph_rule = "4-6 substantive paragraphs" if mode == "fast" else "6-8 substantive paragraphs"
    return f"""You are a journalist at Signal, a news-transparency platform that shows readers how multiple outlets cover the same story.

Topic: {query}

SOURCE MATERIAL ({n_sources} sources):
---
{source_block}
---

Write a factual news article based ONLY on the source material above. Follow these rules exactly:

1. {paragraph_rule}, Associated Press style, plain prose only.
2. Lead paragraph: the single most important confirmed fact.
3. Middle paragraphs: include the concrete details available in the sources: agencies, places, people, numbers, timing, policy terms, company names, and source-specific caveats when present.
4. Attribute key details to specific outlets ("AP reported that...", "According to The Guardian,..."). Where 2+ sources confirm the same fact, state it as established. Where only 1 source reports something, attribute it.
5. Final paragraph: meaningful context or background, not a generic wrap-up.
6. Do NOT invent any fact, quote, statistic, or name not present in the source material above.
7. Correct all grammar and spelling. Write at a professional newspaper standard.
8. Return EXACTLY this format and nothing else:

<<<HEADLINE>>>
A specific factual news headline, 8-14 words, no clickbait, do not mention Signal
<<<DEK>>>
A one-sentence summary under 24 words
<<<BODY>>>
paragraph 1

paragraph 2

..."""


def _emit_stream_progress(accumulated: str, on_chunk) -> None:
    if not on_chunk:
        return
    package = _parse_package_text(accumulated) or {}
    body = package.get("body") or ""
    headline = package.get("headline") or ""
    dek = package.get("dek") or ""
    # Partial streams often fail the full-package length gates; still surface
    # tagged fields so image lookup can start before the draft is finished.
    if not headline:
        headline_match = re.search(r"<<<HEADLINE>>>\s*(.+)", accumulated)
        if headline_match:
            headline = headline_match.group(1).strip().strip('"')
    if not dek:
        dek_match = re.search(r"<<<DEK>>>\s*(.+)", accumulated)
        if dek_match:
            dek = dek_match.group(1).strip().strip('"')
    if "<<<BODY>>>" in accumulated and not body:
        body = accumulated.split("<<<BODY>>>", 1)[-1].strip()
    on_chunk({
        "draft_text": body or accumulated[-1200:],
        "headline": headline,
        "dek": dek,
    })



def _call_gemini_package(
    *,
    model: str,
    payload: bytes,
    key: str,
    timeout: int = 30,
    stream: bool = False,
    on_chunk=None,
) -> str | None:
    if stream:
        url = f"{_API_BASE}/{urllib.parse.quote(model, safe='')}:streamGenerateContent?alt=sse"
    else:
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
    if not stream:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        return text if len(text) > 100 else None

    accumulated = ""
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        while True:
            line = resp.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="ignore").strip()
            if not decoded.startswith("data:"):
                continue
            data_str = decoded[5:].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                payload_obj = json.loads(data_str)
            except Exception:
                continue
            parts = payload_obj.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            delta = parts[0].get("text", "") if parts else ""
            if not delta:
                continue
            accumulated += delta
            _emit_stream_progress(accumulated, on_chunk)
    return accumulated if len(accumulated) > 100 else None


def write_article_package_with_gemini(
    query: str,
    source_articles: list[dict],
    *,
    mode: str = "thorough",
    on_chunk=None,
) -> dict[str, str] | None:
    """
    One Gemini call that returns headline + dek + body.

    Fast mode uses the lite model and a smaller source budget. When on_chunk is
    provided, stream tokens so callers can inspect the draft before publish
    (for example to pick an article image) without showing a partial article.
    """
    key = settings.gemini_api_key
    if not key:
        _set_last_error(kind="config", message="GEMINI_API_KEY is not set")
        return None

    if _rate_limited():
        _set_last_error(kind="rate_limit", message="Local Gemini rate cap reached")
        print("[Gemini] Local rate cap reached — skipping to preserve quota.", file=sys.stderr)
        return None

    source_block, n_sources = _build_source_block(source_articles, mode=mode)
    if not source_block:
        _set_last_error(kind="input", message="No source material was available for Gemini")
        return None

    model = _active_model(mode)
    _clear_last_error()
    prompt = _package_prompt(query, source_block, n_sources, mode)
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.25,
            "maxOutputTokens": 1400 if mode == "fast" else 1600,
            "topP": 0.9,
        },
    }).encode("utf-8")
    use_stream = on_chunk is not None

    try:
        text = _call_gemini_package(
            model=model,
            payload=payload,
            key=key,
            timeout=20 if mode == "fast" else 24,
            stream=use_stream,
            on_chunk=on_chunk,
        )
        package = _parse_package_text(text or "")
        if package and package.get("body"):
            return package

        _set_last_error(kind="response", model=model, message="Gemini returned an unusable article package")
        return None

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
        if exc.code in (404, 429):
            fallback_model = _MODEL_ALIAS_FALLBACK if exc.code == 404 else _MODEL_LITE_FALLBACK
            print(f"[Gemini] HTTP {exc.code} detail — status: {status}, message: {str(message)[:200]}", file=sys.stderr)
            if model != fallback_model:
                print(f"[Gemini] Trying fallback model {fallback_model}…", file=sys.stderr)
                try:
                    text = _call_gemini_package(
                        model=fallback_model,
                        payload=payload,
                        key=key,
                        timeout=30,
                        stream=use_stream,
                        on_chunk=on_chunk,
                    )
                    package = _parse_package_text(text or "")
                    if package and package.get("body"):
                        print(f"[Gemini] Fallback to {fallback_model} succeeded.", file=sys.stderr)
                        _set_last_error(kind="fallback", model=fallback_model, original_model=model, original_http_status=exc.code)
                        return package
                except Exception as fe:
                    print(f"[Gemini] Fallback also failed: {fe}", file=sys.stderr)
            if exc.code == 429:
                _record_429()
                print("[Gemini] 65 s cooldown started.", file=sys.stderr)
        else:
            print(f"[Gemini] HTTP {exc.code}: {message}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="request", model=model, message=str(exc))
        print(f"[Gemini] Request failed: {exc}", file=sys.stderr)
        return None


def write_article_with_gemini(
    query: str,
    source_articles: list[dict],
    *,
    mode: str = "thorough",
    on_chunk=None,
) -> str | None:
    """
    Compatibility wrapper: return article body text from the packaged writer.
    """
    package = write_article_package_with_gemini(
        query,
        source_articles,
        mode=mode,
        on_chunk=on_chunk,
    )
    if not package:
        return None
    return package.get("body") or None


def suggest_follow_up_prompts_with_gemini(
    topic: str,
    headline: str,
    dek: str,
    body_paragraphs: list[str] | None = None,
    max_prompts: int = 5,
) -> list[str] | None:
    """
    Ask Gemini for short follow-up search prompts that help a reader keep
    exploring a story: adjacent angles, consequences, background, and open
    questions — not rephrasings of the original headline.

    Returns a list of prompt strings, or None when Gemini is unavailable.
    """
    key = settings.gemini_api_key
    if not key:
        _set_last_error(kind="config", message="GEMINI_API_KEY is not set")
        return None
    if _rate_limited():
        _set_last_error(kind="rate_limit", message="Local Gemini rate cap reached")
        return None

    body = "\n\n".join(p.strip() for p in (body_paragraphs or []) if p and p.strip())
    body_block = f"Opening paragraphs:\n{body[:2200]}" if body else ""
    model = _active_model("thorough")
    _clear_last_error()

    prompt = f"""You are a research editor at Signal, a news exploration platform.

A reader just finished this article:
Topic searched: {topic or headline}
Headline: {headline}
Summary: {dek}
{body_block}

Suggest {max_prompts} follow-up searches that would genuinely help this reader continue exploring.

Rules:
1. Each suggestion must open a DIFFERENT angle: consequences, affected people or industries, historical background, policy or regulatory response, money and markets, opposing viewpoints, or what to watch next.
2. Do NOT rephrase the headline or swap a single word. Each suggestion must introduce a new dimension of the story.
3. Each suggestion is a natural search phrase of 4-9 words, in plain language. No quotation marks, no numbering, no trailing punctuation.
4. Suggestions must stay grounded in the topic above — no invented events or names.
5. Return strict JSON only: an array of {max_prompts} strings. No markdown, no code fence, no explanation."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.55,
            "maxOutputTokens": 320,
            "topP": 0.92,
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
        with urllib.request.urlopen(req, timeout=14) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = parts[0].get("text", "").strip() if parts else ""
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("Gemini follow-ups were not a JSON array")
        prompts: list[str] = []
        for item in parsed:
            cleaned = str(item).strip().strip('"').strip()
            if 3 <= len(cleaned.split()) <= 12 and cleaned.lower() not in {p.lower() for p in prompts}:
                prompts.append(cleaned)
        return prompts[:max_prompts] or None
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _record_429()
        _set_last_error(kind="follow_up_http", model=model, http_status=exc.code, message=str(exc))
        print(f"[Gemini] Follow-up generation HTTP {exc.code}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="follow_up_request", model=model, message=str(exc))
        print(f"[Gemini] Follow-up generation failed: {exc}", file=sys.stderr)
        return None


def write_article_header_with_gemini(
    query: str,
    body_paragraphs: list[str],
    source_articles: list[dict],
) -> dict[str, str] | None:
    """
    Generate display headline and dek from the finished article body.
    Falls back cleanly when Gemini is unavailable or returns invalid JSON.
    """
    key = settings.gemini_api_key
    if not key:
        _set_last_error(kind="config", message="GEMINI_API_KEY is not set")
        return None
    if _rate_limited():
        _set_last_error(kind="rate_limit", message="Local Gemini rate cap reached")
        return None

    body = "\n\n".join(p.strip() for p in body_paragraphs if p and p.strip())
    if len(body) < 180:
        _set_last_error(kind="input", message="Article body was too short for headline generation")
        return None

    source_names = sorted({str(a.get("source_name") or "").strip() for a in source_articles if a.get("source_name")})
    model = _active_model("thorough")
    _clear_last_error()

    prompt = f"""You are a senior news editor at Signal.

Topic requested by reader: {query}
Sources reviewed: {", ".join(source_names[:6]) or "public source material"}

Finished article body:
---
{body[:6500]}
---

Write the article display header based ONLY on the finished article body.

Return strict JSON only, with exactly these keys:
{{
  "headline": "A specific, factual news headline, 8-14 words, no clickbait",
  "dek": "A one-sentence summary under 24 words"
}}

Rules:
1. Do not add facts that are not in the body.
2. Do not mention Signal in the headline.
3. Do not use vague words like scrutiny, questions, situation, or developments unless the body is genuinely about process.
4. Prefer the most concrete confirmed outcome in the lead paragraph.
5. No markdown, no code fence, no explanation."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 220,
            "topP": 0.85,
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
        with urllib.request.urlopen(req, timeout=18) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = parts[0].get("text", "").strip() if parts else ""
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        headline = str(parsed.get("headline", "")).strip().strip('"')
        dek = str(parsed.get("dek", "")).strip().strip('"')
        if len(headline.split()) < 4 or len(headline) > 150:
            raise ValueError("Gemini headline failed length validation")
        if len(dek.split()) < 5 or len(dek) > 220:
            raise ValueError("Gemini dek failed length validation")
        return {"headline": headline, "dek": dek}
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _record_429()
        _set_last_error(kind="header_http", model=model, http_status=exc.code, message=str(exc))
        print(f"[Gemini] Header generation HTTP {exc.code}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="header_request", model=model, message=str(exc))
        print(f"[Gemini] Header generation failed: {exc}", file=sys.stderr)
        return None
