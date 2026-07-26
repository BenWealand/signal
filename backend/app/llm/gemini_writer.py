from __future__ import annotations

import collections
import json
import logging
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app.config import settings

logger = logging.getLogger(__name__)

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
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


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


def describe_last_gemini_error() -> str:
    """Return a safe, actionable explanation for the most recent failed write."""
    error = get_last_gemini_error()
    if not error:
        return "Gemini did not return an article."

    kind = str(error.get("kind") or "")
    attempted = error.get("attempted_models")
    attempt_count = len(attempted) if isinstance(attempted, list) else 1
    attempt_note = f" after trying {attempt_count} models" if attempt_count > 1 else ""
    message = re.sub(r"\s+", " ", str(error.get("message") or "")).strip()[:240]

    if kind == "http":
        status = int(error.get("http_status") or 0)
        if status == 429:
            return f"Gemini rate-limited this request{attempt_note} (HTTP 429). Try again after one minute."
        if status in _RETRYABLE_HTTP_STATUSES:
            detail = f": {message}" if message else ""
            return f"Gemini is temporarily unavailable{attempt_note} (HTTP {status}{detail}). Try again shortly."
        detail = f": {message}" if message else ""
        return f"Gemini rejected the article request{attempt_note} (HTTP {status}{detail})."
    if kind == "response":
        return f"Gemini returned an incomplete article package{attempt_note}. Please retry the request."
    if kind == "rate_limit":
        return "Signal's Gemini request limit was reached. Try again after one minute."
    if kind == "config":
        return "Gemini is not configured on the backend."
    if kind == "input":
        return "No accessible source material was available for Gemini."
    if kind == "request":
        detail = f": {message}" if message else ""
        return f"Gemini could not be reached{attempt_note}{detail}."
    return message or "Gemini did not return an article."


def _alternate_model(model: str, http_status: int | None = None) -> str:
    """Choose a genuinely different Flash capacity pool for one bounded retry."""
    if http_status == 404 and model != _MODEL_ALIAS_FALLBACK:
        return _MODEL_ALIAS_FALLBACK
    if "lite" in model.lower():
        return _MODEL_ALIAS_FALLBACK
    return _MODEL_LITE_FALLBACK


def _http_error_details(exc: urllib.error.HTTPError, model: str) -> dict[str, object]:
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
    return {
        "kind": "http",
        "model": model,
        "http_status": exc.code,
        "api_status": status,
        "reason": reason,
        "message": message,
    }


def _sleep_before_retry() -> None:
    """Use a short bounded backoff so transient provider capacity can recover."""
    time.sleep(1.0 + random.uniform(0.0, 0.35))


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

    primary_model = _active_model(mode)
    _clear_last_error()
    prompt = _package_prompt(query, source_block, n_sources, mode)
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 1400 if mode == "fast" else 1600,
        },
    }).encode("utf-8")
    use_stream = on_chunk is not None

    models = [primary_model, _alternate_model(primary_model)]
    attempted_models: list[str] = []
    attempt_errors: list[dict[str, object]] = []

    for attempt_index, model in enumerate(models):
        if model in attempted_models:
            continue
        attempted_models.append(model)
        try:
            text = _call_gemini_package(
                model=model,
                payload=payload,
                key=key,
                timeout=(20 if mode == "fast" else 24) if attempt_index == 0 else 30,
                stream=use_stream,
                on_chunk=on_chunk,
            )
            package = _parse_package_text(text or "")
            if package and package.get("body"):
                if attempt_index:
                    logger.info(
                        "Gemini article model failover succeeded primary=%s fallback=%s",
                        primary_model,
                        model,
                    )
                _clear_last_error()
                return package

            error = {
                "kind": "response",
                "model": model,
                "message": "Gemini returned an unusable article package",
            }
            attempt_errors.append(error)
            _set_last_error(
                **error,
                attempted_models=list(attempted_models),
                attempt_errors=list(attempt_errors),
            )
            logger.warning("Gemini returned an unusable article package model=%s", model)
            if attempt_index == 0:
                logger.info("Retrying Gemini article with alternate model=%s", models[1])
                continue
            return None
        except urllib.error.HTTPError as exc:
            error = _http_error_details(exc, model)
            attempt_errors.append(error)
            _set_last_error(
                **error,
                attempted_models=list(attempted_models),
                attempt_errors=list(attempt_errors),
            )
            logger.warning(
                "Gemini article request failed model=%s http_status=%s api_status=%s message=%s",
                model,
                exc.code,
                error.get("api_status"),
                str(error.get("message") or "")[:200],
            )
            retryable = exc.code == 404 or exc.code in _RETRYABLE_HTTP_STATUSES
            if attempt_index == 0 and retryable:
                fallback_model = _alternate_model(model, exc.code)
                models[1] = fallback_model
                logger.info(
                    "Retrying Gemini article primary=%s fallback=%s http_status=%s",
                    model,
                    fallback_model,
                    exc.code,
                )
                if exc.code in _RETRYABLE_HTTP_STATUSES:
                    _sleep_before_retry()
                continue
            if any(int(item.get("http_status") or 0) == 429 for item in attempt_errors):
                _record_429()
                logger.warning("Gemini cooldown started after exhausted HTTP 429 retries")
            return None
        except Exception as exc:
            error = {
                "kind": "request",
                "model": model,
                "message": str(exc),
            }
            attempt_errors.append(error)
            _set_last_error(
                **error,
                attempted_models=list(attempted_models),
                attempt_errors=list(attempt_errors),
            )
            logger.warning("Gemini article request failed model=%s error=%s", model, exc)
            if attempt_index == 0:
                logger.info("Retrying Gemini article with alternate model=%s", models[1])
                continue
            return None

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
            "maxOutputTokens": 320,
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


def suggest_image_queries_with_gemini(
    headline: str = "",
    dek: str = "",
    body_paragraphs: list[str] | None = None,
    *,
    topic: str = "",
    max_queries: int = 5,
) -> list[str] | None:
    """
    Ask Gemini for concrete photographic Openverse search queries.

    Prefer calling this after the article is finished so queries reflect the
    final story. Ranked ideas should be specific — people first, then named
    teams/events/objects — never broad topic words alone.
    """
    key = settings.gemini_api_key
    if not key:
        return None
    if _rate_limited():
        return None

    body = "\n\n".join(p.strip() for p in (body_paragraphs or []) if p and p.strip())
    body_block = body[:3200]
    model = _active_model("fast")
    _clear_last_error()
    limit = max(1, min(int(max_queries), 5))
    topic_line = (topic or headline or "").strip()
    finished = bool(body_block.strip())

    prompt = f"""You are a photo editor choosing the best Openverse search queries for a news story.

User topic / prompt: {topic_line}
Headline: {headline}
Summary: {dek}
Article body:
{body_block or "(not written yet — choose from the user topic/prompt only)"}

{"Read the finished article carefully. Suggest your TOP " + str(limit) + " best image ideas, ranked by relevance to this specific story (best first)." if finished else f"Suggest {limit} short image search queries for openly licensed photos that would clearly illustrate THIS story."}

Rules:
1. Prefer named people first (athletes, officials, executives, speakers) when the article names them.
2. Otherwise choose a specific named team, product, building, event, landmark, or object that appears in the article.
3. Every query must be concrete and photographic (2-6 words). A reader should be able to picture the photo.
4. NEVER return a broad/generic query. Reject examples like "Spain", "economy", "interest rates", "climate change", "technology", "football", or any other topic-only phrase.
5. If a country/city/company is relevant, pair it with a concrete visual subject grounded in the article (flag, national team, leader/president/CEO, stadium, product, protest, etc.).
6. Do NOT invent names or details that are not in the topic/article.
7. Rank by relevance: idea #1 must be the single best illustration of the article.
8. Return strict JSON only: an array of exactly {limit} strings, best first. No markdown, no explanation."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 220,
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
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = parts[0].get("text", "").strip() if parts else ""
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("Gemini image queries were not a JSON array")
        queries: list[str] = []
        for item in parsed:
            cleaned = re.sub(r"\s+", " ", str(item).strip().strip('"').strip())
            words = cleaned.split()
            if not (2 <= len(words) <= 8):
                continue
            lowered = cleaned.lower()
            if lowered in {q.lower() for q in queries}:
                continue
            if len(words) == 1:
                continue
            queries.append(cleaned)
        return queries[:limit] or None
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _record_429()
        _set_last_error(kind="image_query_http", model=model, http_status=exc.code, message=str(exc))
        print(f"[Gemini] Image-query generation HTTP {exc.code}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="image_query_request", model=model, message=str(exc))
        print(f"[Gemini] Image-query generation failed: {exc}", file=sys.stderr)
        return None


def match_x_posts_to_articles_with_gemini(
    posts: list[dict],
    articles: list[dict],
) -> list[dict] | None:
    """
    Match X posts to already-written Signal articles.

    Returns a list of {postId, articleId, confidence, reason} dicts, or None when
    Gemini is unavailable.
    """
    key = settings.gemini_api_key
    if not key:
        return None
    if _rate_limited():
        return None
    if not posts or not articles:
        return []

    post_lines = []
    for post in posts[:40]:
        post_id = str(post.get("postId") or "").strip()
        text = re.sub(r"\s+", " ", str(post.get("text") or post.get("topic") or "")).strip()[:280]
        author = str(post.get("author") or "").strip()
        if not post_id:
            continue
        post_lines.append(f"- postId={post_id} author=@{author or 'unknown'} text={text or '(empty)'}")

    article_lines = []
    for article in articles[:80]:
        article_id = str(article.get("id") or "").strip()
        headline = str(article.get("headline") or "").strip()
        if not article_id or not headline:
            continue
        dek = str(article.get("dek") or "").strip()[:160]
        section = str(article.get("section") or "latest")
        article_lines.append(f"- articleId={article_id} section={section} headline={headline} dek={dek}")

    if not post_lines or not article_lines:
        return []

    model = _active_model("fast")
    _clear_last_error()
    prompt = f"""You are matching X/Twitter posts to already-written Signal news articles.

X posts:
{chr(10).join(post_lines)}

Ready Signal articles:
{chr(10).join(article_lines)}

For EACH post, choose the single best matching article, or none if no article clearly covers the same story.
Rules:
1. Prefer topical overlap of people, orgs, events, and places.
2. Do not invent articleIds. Only use ids from the article list.
3. One article should not be reused for multiple posts unless it is clearly the only fit.
4. confidence is a number from 0 to 1.
5. Return strict JSON only: an array of objects with keys postId, articleId, confidence, reason.
6. If unmatched, set articleId to "" and confidence to 0."""

    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 1200,
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
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = parts[0].get("text", "").strip() if parts else ""
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("Gemini match payload was not a JSON array")
        valid_articles = {str(item.get("id") or "") for item in articles}
        valid_posts = {str(item.get("postId") or "") for item in posts}
        results: list[dict] = []
        used_articles: set[str] = set()
        for item in parsed:
            if not isinstance(item, dict):
                continue
            post_id = str(item.get("postId") or "").strip()
            article_id = str(item.get("articleId") or "").strip()
            if post_id not in valid_posts:
                continue
            if article_id and article_id not in valid_articles:
                article_id = ""
            if article_id and article_id in used_articles:
                article_id = ""
            if article_id:
                used_articles.add(article_id)
            try:
                confidence = float(item.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            if not article_id:
                confidence = 0.0
            results.append(
                {
                    "postId": post_id,
                    "articleId": article_id,
                    "confidence": confidence,
                    "reason": str(item.get("reason") or "").strip()[:160],
                }
            )
        # Ensure every post appears once.
        seen_posts = {row["postId"] for row in results}
        for post_id in valid_posts:
            if post_id not in seen_posts:
                results.append(
                    {
                        "postId": post_id,
                        "articleId": "",
                        "confidence": 0.0,
                        "reason": "no match returned",
                    }
                )
        return results
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _record_429()
        _set_last_error(kind="x_match_http", model=model, http_status=exc.code, message=str(exc))
        print(f"[Gemini] X-match HTTP {exc.code}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="x_match_request", model=model, message=str(exc))
        print(f"[Gemini] X-match failed: {exc}", file=sys.stderr)
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
            "maxOutputTokens": 220,
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
