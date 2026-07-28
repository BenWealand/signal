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
import urllib.request

from app.config import settings

logger = logging.getLogger(__name__)

# OpenCode Zen — OpenAI-compatible chat completions gateway.
# Docs: https://opencode.ai/docs/zen/
_API_BASE = "https://opencode.ai/zen/v1"
_CHAT_URL = f"{_API_BASE}/chat/completions"

# Per-article token budget: keep prompt under ~6 000 chars of source material.
_MAX_SOURCE_CHARS = 9_000
_MAX_PER_ARTICLE = 1_300
_FAST_MAX_SOURCE_CHARS = 5_500
_FAST_MAX_PER_ARTICLE = 900

# Local rate limiter (Zen is pay-per-use; still avoid stampedes).
_RATE_LIMIT = 10
_RATE_WINDOW = 60.0
_COOLDOWN_AFTER_429 = 65.0

_rate_lock = threading.Lock()
_call_times: collections.deque[float] = collections.deque()
_last_429_at: float = 0.0
_last_error_lock = threading.Lock()
_last_error: dict[str, object] | None = None

# Legacy Google Gemini model ids that may still be set via GEMINI_MODEL on Render.
# Remap them to OpenCode Zen chat-completions models.
_LEGACY_GEMINI_MODELS = frozenset({
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
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-9.9-flash-custom",
})
_MODEL_PRIMARY = "deepseek-v4-flash"
_MODEL_FALLBACK = "minimax-m2.7"
_MODEL_FAST = "deepseek-v4-flash"
# Free OpenCode Zen models — used when paid models return 401/403/404.
_MODEL_FREE_CHAIN = (
    "deepseek-v4-flash-free",
    "big-pickle",
    "mimo-v2.5-free",
    "ling-3.0-flash-free",
)
_RETRYABLE_HTTP_STATUSES = frozenset({401, 403, 408, 429, 500, 502, 503, 504})


def _api_key() -> str:
    # Prefer OpenCode Zen; accept legacy gemini_api_key attrs used by older tests/env.
    return (
        str(getattr(settings, "opencode_api_key", "") or "")
        or str(getattr(settings, "gemini_api_key", "") or "")
    ).strip()


def _auth_headers(key: str) -> dict[str, str]:
    """
    OpenCode Zen's OpenAI-compatible surface accepts Bearer.
    Some gateway paths also check x-api-key — send both so neither path 401/403s.
    """
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "x-api-key": key,
    }


def _active_model(mode: str = "thorough") -> str:
    if mode == "fast":
        model = (
            str(getattr(settings, "opencode_fast_model", "") or "")
            or str(getattr(settings, "gemini_fast_model", "") or "")
        ).strip() or _MODEL_FAST
    else:
        model = (
            str(getattr(settings, "opencode_model", "") or "")
            or str(getattr(settings, "gemini_model", "") or "")
        ).strip() or _MODEL_PRIMARY
    lowered = model.lower()
    if lowered in _LEGACY_GEMINI_MODELS or lowered.startswith("gemini-"):
        mapped = _MODEL_FAST if mode == "fast" else _MODEL_PRIMARY
        print(
            f"[Zen] Model {model} is a legacy Gemini id — using OpenCode Zen model {mapped} instead.",
            file=sys.stderr,
        )
        return mapped
    return model


def _model_failover_chain(primary: str) -> list[str]:
    """Ordered unique models to try when the primary is denied or unavailable."""
    chain = [primary, _alternate_model(primary), *_MODEL_FREE_CHAIN, _MODEL_PRIMARY, _MODEL_FALLBACK]
    seen: set[str] = set()
    ordered: list[str] = []
    for model in chain:
        name = (model or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


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


def get_last_zen_error() -> dict[str, object] | None:
    with _last_error_lock:
        return dict(_last_error) if _last_error else None


def describe_last_zen_error() -> str:
    """Return a safe, actionable explanation for the most recent failed write."""
    error = get_last_zen_error()
    if not error:
        return "OpenCode Zen did not return an article."

    kind = str(error.get("kind") or "")
    attempted = error.get("attempted_models")
    attempt_count = len(attempted) if isinstance(attempted, list) else 1
    attempt_note = f" after trying {attempt_count} models" if attempt_count > 1 else ""
    message = re.sub(r"\s+", " ", str(error.get("message") or "")).strip()[:240]

    if kind == "http":
        status = int(error.get("http_status") or 0)
        if status == 401:
            return (
                f"OpenCode Zen rejected the API key{attempt_note} (HTTP 401). "
                "Set OPENCODE_API_KEY to a valid key from https://opencode.ai/auth."
            )
        if status == 403:
            return (
                f"OpenCode Zen forbade this model or key{attempt_note} (HTTP 403). "
                "Enable the model in your Zen workspace, check billing, or set OPENCODE_MODEL "
                "to an allowed chat model such as deepseek-v4-flash or deepseek-v4-flash-free."
            )
        if status == 429:
            return f"OpenCode Zen rate-limited this request{attempt_note} (HTTP 429). Try again after one minute."
        if status in _RETRYABLE_HTTP_STATUSES:
            detail = f": {message}" if message else ""
            return f"OpenCode Zen is temporarily unavailable{attempt_note} (HTTP {status}{detail}). Try again shortly."
        detail = f": {message}" if message else ""
        return f"OpenCode Zen rejected the article request{attempt_note} (HTTP {status}{detail})."
    if kind == "response":
        return f"OpenCode Zen returned an incomplete article package{attempt_note}. Please retry the request."
    if kind == "rate_limit":
        return "Signal's OpenCode Zen request limit was reached. Try again after one minute."
    if kind == "config":
        return "OpenCode Zen is not configured on the backend (set OPENCODE_API_KEY)."
    if kind == "input":
        return "No accessible source material was available for OpenCode Zen."
    if kind == "request":
        detail = f": {message}" if message else ""
        return f"OpenCode Zen could not be reached{attempt_note}{detail}."
    return message or "OpenCode Zen did not return an article."


# Backward-compatible aliases while call sites migrate off Gemini names.
get_last_gemini_error = get_last_zen_error
describe_last_gemini_error = describe_last_zen_error


def _alternate_model(model: str, http_status: int | None = None) -> str:
    """Choose a different Zen chat model for one bounded retry."""
    if model != _MODEL_FALLBACK:
        return _MODEL_FALLBACK
    return _MODEL_PRIMARY if model != _MODEL_PRIMARY else _MODEL_FAST


def _http_error_details(exc: urllib.error.HTTPError, model: str) -> dict[str, object]:
    body: dict[str, object] = {}
    try:
        body = json.loads(exc.read().decode("utf-8", errors="ignore"))
    except Exception:
        body = {}
    details = body.get("error", {}) if isinstance(body, dict) else {}
    if isinstance(details, dict):
        message = details.get("message") or details.get("type") or str(exc)
        status = details.get("code") or details.get("type")
    else:
        message = str(details or exc)
        status = None
    return {
        "kind": "http",
        "model": model,
        "http_status": exc.code,
        "api_status": status,
        "message": message,
    }


def _sleep_before_retry() -> None:
    time.sleep(1.0 + random.uniform(0.0, 0.35))


def _rate_limited() -> bool:
    now = time.monotonic()
    with _rate_lock:
        if now - _last_429_at < _COOLDOWN_AFTER_429:
            remaining = int(_COOLDOWN_AFTER_429 - (now - _last_429_at))
            print(f"[Zen] In 429 cooldown — {remaining}s remaining.", file=sys.stderr)
            return True
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
        title = (art.get("title") or "").strip()
        body = (art.get("clean_text") or art.get("raw_text") or "").strip()
        if not title and not body:
            continue
        text = body[:max_per_article] if body else ""
        block = f"[{source}]\nTitle: {title}\n{text}".strip()
        blocks.append(block)
        total += len(block)
        if total >= max_source_chars:
            break

    return "\n---\n".join(blocks), len(blocks)


def _validated_package(headline_value: object, dek_value: object, body_value: object) -> dict[str, str] | None:
    headline = str(headline_value or "").strip().strip('"')
    dek = str(dek_value or "").strip().strip('"')
    if isinstance(body_value, list):
        paragraphs = [str(item or "").strip() for item in body_value]
    else:
        body_text = str(body_value or "").strip()
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body_text) if part.strip()]
        if len(paragraphs) < 2:
            paragraphs = [line.strip() for line in body_text.splitlines() if len(line.strip()) > 60]
    paragraphs = [paragraph for paragraph in paragraphs if len(paragraph) >= 40]
    body = "\n\n".join(paragraphs)
    if (
        len(headline.split()) >= 4
        and len(dek.split()) >= 5
        and len(paragraphs) >= 2
        and len(body) > 100
    ):
        return {"headline": headline, "dek": dek, "body": body}
    return None


def _parse_package_text(text: str) -> dict[str, str] | None:
    """Parse and validate a complete Zen-authored article package."""
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            package = _validated_package(
                parsed.get("headline"),
                parsed.get("dek"),
                parsed.get("body"),
            )
            if package:
                return package
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    headline_match = re.search(r"<<<HEADLINE>>>\s*(.+)", cleaned)
    dek_match = re.search(r"<<<DEK>>>\s*(.+)", cleaned)
    body_match = re.search(r"<<<BODY>>>\s*([\s\S]+)", cleaned)
    if headline_match and dek_match and body_match:
        return _validated_package(
            headline_match.group(1),
            dek_match.group(1),
            body_match.group(1),
        )
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
8. Return one complete article package as strict JSON with keys headline, dek, and body.
   - headline: specific factual news headline of 8-14 words. Do not mention Signal.
   - dek: one-sentence factual summary under 24 words.
   - body: array of separate substantive prose paragraphs (2-8 items).
No markdown. No code fence. JSON only."""


def _emit_stream_progress(accumulated: str, on_chunk) -> None:
    if not on_chunk:
        return
    package = _parse_package_text(accumulated) or {}
    body = package.get("body") or ""
    headline = package.get("headline") or ""
    dek = package.get("dek") or ""
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


def _message_content(data: dict) -> str:
    """Extract assistant text from an OpenAI-compatible chat completion."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
        return "".join(parts).strip()
    if content is None:
        # Some gateways put text on the choice itself.
        return str(choice.get("text") or "").strip()
    return str(content).strip()


def _call_zen_chat(
    *,
    model: str,
    prompt: str,
    key: str,
    max_tokens: int,
    timeout: int = 30,
    json_mode: bool = True,
    stream: bool = False,
    on_chunk=None,
) -> str | None:
    payload_obj: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    if json_mode:
        payload_obj["response_format"] = {"type": "json_object"}
    if stream:
        payload_obj["stream"] = True

    payload = json.dumps(payload_obj).encode("utf-8")
    req = urllib.request.Request(
        _CHAT_URL,
        data=payload,
        headers=_auth_headers(key),
        method="POST",
    )

    if not stream:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("error"):
            _set_last_error(kind="api", model=model, error=data["error"])
            print(f"[Zen] API error: {data['error']}", file=sys.stderr)
            return None
        text = _message_content(data if isinstance(data, dict) else {})
        if not text:
            _set_last_error(kind="response", model=model, message="OpenCode Zen returned no final text")
            return None
        return text

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
                chunk = json.loads(data_str)
            except Exception:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece is None and "text" in delta:
                piece = delta.get("text")
            if not piece:
                continue
            accumulated += str(piece)
            _emit_stream_progress(accumulated, on_chunk)
    return accumulated or None


def write_article_package_with_zen(
    query: str,
    source_articles: list[dict],
    *,
    mode: str = "thorough",
    on_chunk=None,
) -> dict[str, str] | None:
    """
    One Zen call that returns headline + dek + body.

    Fast mode uses the configured fast model and a smaller source budget.
    """
    key = _api_key()
    if not key:
        _set_last_error(kind="config", message="OPENCODE_API_KEY is not set")
        return None

    if _rate_limited():
        _set_last_error(kind="rate_limit", message="Local OpenCode Zen rate cap reached")
        print("[Zen] Local rate cap reached — skipping to preserve quota.", file=sys.stderr)
        return None

    source_block, n_sources = _build_source_block(source_articles, mode=mode)
    if not source_block:
        _set_last_error(kind="input", message="No source material was available for OpenCode Zen")
        return None

    primary_model = _active_model(mode)
    _clear_last_error()
    prompt = _package_prompt(query, source_block, n_sources, mode)
    use_stream = False

    models = _model_failover_chain(primary_model)
    attempted_models: list[str] = []
    attempt_errors: list[dict[str, object]] = []

    for attempt_index, model in enumerate(models):
        if model in attempted_models:
            continue
        attempted_models.append(model)
        try:
            text = _call_zen_chat(
                model=model,
                prompt=prompt,
                key=key,
                max_tokens=2400 if mode == "fast" else 3600,
                timeout=(20 if mode == "fast" else 24) if attempt_index == 0 else 30,
                json_mode=True,
                stream=use_stream,
                on_chunk=on_chunk,
            )
            package = _parse_package_text(text or "")
            if package and package.get("body"):
                if on_chunk:
                    try:
                        on_chunk({
                            "draft_text": package["body"],
                            "headline": package["headline"],
                            "dek": package["dek"],
                        })
                    except Exception:
                        logger.exception("Zen article completion callback failed")
                if attempt_index:
                    logger.info(
                        "Zen article model failover succeeded primary=%s fallback=%s",
                        primary_model,
                        model,
                    )
                _clear_last_error()
                return package

            call_error = get_last_zen_error()
            if not text and call_error and call_error.get("model") == model:
                error = {
                    key_name: value
                    for key_name, value in call_error.items()
                    if key_name != "timestamp"
                }
            else:
                error = {
                    "kind": "response",
                    "model": model,
                    "message": "OpenCode Zen returned an unusable article package",
                }
            error["response_length"] = len(text or "")
            attempt_errors.append(error)
            _set_last_error(
                **error,
                attempted_models=list(attempted_models),
                attempt_errors=list(attempt_errors),
            )
            logger.warning(
                "Zen returned an unusable article package model=%s response_length=%s",
                model,
                error["response_length"],
            )
            if attempt_index + 1 < len(models):
                logger.info("Retrying Zen article with alternate model=%s", models[attempt_index + 1])
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
                "Zen article request failed model=%s http_status=%s api_status=%s message=%s",
                model,
                exc.code,
                error.get("api_status"),
                str(error.get("message") or "")[:200],
            )
            # Some models reject response_format; retry once without it on 400/403.
            if exc.code in {400, 403}:
                try:
                    text = _call_zen_chat(
                        model=model,
                        prompt=prompt,
                        key=key,
                        max_tokens=2400 if mode == "fast" else 3600,
                        timeout=30,
                        json_mode=False,
                        stream=False,
                    )
                    package = _parse_package_text(text or "")
                    if package and package.get("body"):
                        _clear_last_error()
                        return package
                except Exception:
                    logger.exception("Zen article retry without json_mode failed")
            retryable = exc.code == 404 or exc.code in _RETRYABLE_HTTP_STATUSES
            if attempt_index + 1 < len(models) and retryable:
                logger.info(
                    "Retrying Zen article primary=%s fallback=%s http_status=%s",
                    model,
                    models[attempt_index + 1],
                    exc.code,
                )
                if exc.code in {429, 500, 502, 503, 504}:
                    _sleep_before_retry()
                continue
            if any(int(item.get("http_status") or 0) == 429 for item in attempt_errors):
                _record_429()
                logger.warning("Zen cooldown started after exhausted HTTP 429 retries")
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
            logger.warning("Zen article request failed model=%s error=%s", model, exc)
            if attempt_index + 1 < len(models):
                logger.info("Retrying Zen article with alternate model=%s", models[attempt_index + 1])
                continue
            return None

    return None


def write_article_with_zen(
    query: str,
    source_articles: list[dict],
    *,
    mode: str = "thorough",
    on_chunk=None,
) -> str | None:
    """Compatibility wrapper: return article body text from the packaged writer."""
    package = write_article_package_with_zen(
        query,
        source_articles,
        mode=mode,
        on_chunk=on_chunk,
    )
    if not package:
        return None
    return package.get("body") or None


def suggest_follow_up_prompts_with_zen(
    topic: str,
    headline: str,
    dek: str,
    body_paragraphs: list[str] | None = None,
    max_prompts: int = 5,
) -> list[str] | None:
    """Ask Zen for short follow-up search prompts for continuing a story."""
    key = _api_key()
    if not key:
        _set_last_error(kind="config", message="OPENCODE_API_KEY is not set")
        return None
    if _rate_limited():
        _set_last_error(kind="rate_limit", message="Local OpenCode Zen rate cap reached")
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

    try:
        text = _call_zen_chat(
            model=model,
            prompt=prompt,
            key=key,
            max_tokens=320,
            timeout=14,
            json_mode=True,
        ) or ""
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            # Some models wrap the array.
            if isinstance(parsed, dict):
                for value in parsed.values():
                    if isinstance(value, list):
                        parsed = value
                        break
            if not isinstance(parsed, list):
                raise ValueError("Zen follow-ups were not a JSON array")
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
        print(f"[Zen] Follow-up generation HTTP {exc.code}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="follow_up_request", model=model, message=str(exc))
        print(f"[Zen] Follow-up generation failed: {exc}", file=sys.stderr)
        return None


def generic_news_prompt_from_x_posts_with_zen(posts: list[dict]) -> str | None:
    """Turn a mixed batch of social posts into one neutral news-search prompt."""
    key = _api_key()
    if not key:
        _set_last_error(kind="config", message="OPENCODE_API_KEY is not set")
        return None
    if _rate_limited():
        _set_last_error(kind="rate_limit", message="Local OpenCode Zen rate cap reached")
        return None

    post_lines: list[str] = []
    for index, post in enumerate(posts[:50], start=1):
        text = re.sub(r"\s+", " ", str(post.get("text") or "")).strip()[:500]
        url = str(post.get("url") or "").strip()[:300]
        reason = re.sub(r"\s+", " ", str(post.get("reason") or "")).strip()[:300]
        angle = re.sub(r"\s+", " ", str(post.get("angle") or "")).strip()[:300]
        source_assessment = re.sub(
            r"\s+", " ", str(post.get("source_assessment") or "")
        ).strip()[:300]
        if not text:
            continue
        post_lines.append(
            f"{index}. text={text}\n"
            f"   url={url or '(none)'}\n"
            f"   reason={reason or '(none)'}\n"
            f"   angle={angle or '(none)'}\n"
            f"   source_assessment={source_assessment or '(none)'}"
        )
    if not post_lines:
        _set_last_error(kind="input", message="No usable X post text was provided")
        return None

    model = _active_model("fast")
    _clear_last_error()
    prompt = f"""You are an assignment editor choosing one reported news story from a batch of X posts.

Posts:
{chr(10).join(post_lines)}

Choose the strongest concrete event or announcement that is most likely to have recent, independent news coverage. Repeated references to the same event are a useful signal, but one specific official announcement can also qualify.

Rules:
1. Return a neutral web-search prompt of 4-12 words.
2. Name the central person, organization, place, product, or event when the posts provide it.
3. Treat reason, angle, and source_assessment as editorial hints, not verified facts.
4. Remove opinions, insults, ideological framing, engagement bait, and unsupported conclusions.
5. Do not treat a meme, reaction, vague remark, promotional greeting, or allegation as established fact.
6. Phrase uncertain claims as a topic to verify, not as a fact.
7. Do not mention X, tweets, posts, virality, or this batch.
8. Return strict JSON only in this shape: {{"prompt":"..."}}."""

    models = [model]
    fallback_model = _alternate_model(model)
    if fallback_model not in models:
        models.append(fallback_model)

    attempted: list[str] = []
    for index, active_model in enumerate(models):
        attempted.append(active_model)
        try:
            text = _call_zen_chat(
                model=active_model,
                prompt=prompt,
                key=key,
                max_tokens=100,
                timeout=18,
                json_mode=True,
            ) or ""
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            parsed = json.loads(text)
            generic_prompt = re.sub(r"\s+", " ", str(parsed.get("prompt") or "")).strip()
            word_count = len(generic_prompt.split())
            if not generic_prompt or not 3 <= word_count <= 16:
                raise ValueError("Zen returned an unusable news prompt")
            return generic_prompt[:240].rstrip()
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                _record_429()
            retryable = exc.code in _RETRYABLE_HTTP_STATUSES and index + 1 < len(models)
            logger.warning(
                "Zen VM prompt generation HTTP %s with %s%s",
                exc.code,
                active_model,
                "; retrying alternate model" if retryable else "",
            )
            if retryable:
                continue
            _set_last_error(
                kind="http",
                model=active_model,
                attempted_models=attempted,
                http_status=exc.code,
                message=str(exc),
            )
            return None
        except Exception as exc:
            _set_last_error(
                kind="request",
                model=active_model,
                attempted_models=attempted,
                message=str(exc),
            )
            logger.warning("Zen VM prompt generation failed: %s", exc)
            return None
    return None


def suggest_image_queries_with_zen(
    headline: str = "",
    dek: str = "",
    body_paragraphs: list[str] | None = None,
    *,
    topic: str = "",
    max_queries: int = 5,
) -> list[str] | None:
    """Ask Zen for concrete photographic Openverse search queries."""
    key = _api_key()
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

    try:
        text = _call_zen_chat(
            model=model,
            prompt=prompt,
            key=key,
            max_tokens=220,
            timeout=15,
            json_mode=True,
        ) or ""
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            if isinstance(parsed, dict):
                for value in parsed.values():
                    if isinstance(value, list):
                        parsed = value
                        break
            if not isinstance(parsed, list):
                raise ValueError("Zen image queries were not a JSON array")
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
        print(f"[Zen] Image-query generation HTTP {exc.code}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="image_query_request", model=model, message=str(exc))
        print(f"[Zen] Image-query generation failed: {exc}", file=sys.stderr)
        return None


def match_x_posts_to_articles_with_zen(
    posts: list[dict],
    articles: list[dict],
) -> list[dict] | None:
    """Match X posts to already-written Signal articles via Zen."""
    key = _api_key()
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

    try:
        text = _call_zen_chat(
            model=model,
            prompt=prompt,
            key=key,
            max_tokens=1200,
            timeout=20,
            json_mode=True,
        ) or ""
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            for value in parsed.values():
                if isinstance(value, list):
                    parsed = value
                    break
        if not isinstance(parsed, list):
            raise ValueError("Zen match payload was not a JSON array")
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
        print(f"[Zen] X-match HTTP {exc.code}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="x_match_request", model=model, message=str(exc))
        print(f"[Zen] X-match failed: {exc}", file=sys.stderr)
        return None


def write_article_header_with_zen(
    query: str,
    body_paragraphs: list[str],
    source_articles: list[dict],
) -> dict[str, str] | None:
    """Generate display headline and dek from the finished article body."""
    key = _api_key()
    if not key:
        _set_last_error(kind="config", message="OPENCODE_API_KEY is not set")
        return None
    if _rate_limited():
        _set_last_error(kind="rate_limit", message="Local OpenCode Zen rate cap reached")
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

    try:
        text = _call_zen_chat(
            model=model,
            prompt=prompt,
            key=key,
            max_tokens=220,
            timeout=18,
            json_mode=True,
        ) or ""
        if text.startswith("```"):
            text = text.strip("`").removeprefix("json").strip()
        parsed = json.loads(text)
        headline = str(parsed.get("headline", "")).strip().strip('"')
        dek = str(parsed.get("dek", "")).strip().strip('"')
        if len(headline.split()) < 4 or len(headline) > 150:
            raise ValueError("Zen headline failed length validation")
        if len(dek.split()) < 5 or len(dek) > 220:
            raise ValueError("Zen dek failed length validation")
        return {"headline": headline, "dek": dek}
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            _record_429()
        _set_last_error(kind="header_http", model=model, http_status=exc.code, message=str(exc))
        print(f"[Zen] Header generation HTTP {exc.code}: {exc}", file=sys.stderr)
        return None
    except Exception as exc:
        _set_last_error(kind="header_request", model=model, message=str(exc))
        print(f"[Zen] Header generation failed: {exc}", file=sys.stderr)
        return None


# Deprecated Gemini-named wrappers — call Zen under the hood.
write_article_package_with_gemini = write_article_package_with_zen
write_article_with_gemini = write_article_with_zen
suggest_follow_up_prompts_with_gemini = suggest_follow_up_prompts_with_zen
generic_news_prompt_from_x_posts_with_gemini = generic_news_prompt_from_x_posts_with_zen
suggest_image_queries_with_gemini = suggest_image_queries_with_zen
match_x_posts_to_articles_with_gemini = match_x_posts_to_articles_with_zen
write_article_header_with_gemini = write_article_header_with_zen
