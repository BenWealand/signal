from __future__ import annotations

import json
import random
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from app.config import settings

_generation_slots = threading.BoundedSemaphore(max(1, settings.llm_max_concurrency))


_JSON_STRING = r'"(?:\\.|[^"\\])*"'


def _json_string_field(content: str, key: str) -> str:
    match = re.search(rf'{re.escape(json.dumps(key))}\s*:\s*({_JSON_STRING})', content)
    return str(json.loads(match.group(1))) if match else ""


def _recover_partial_article_object(content: str, schema: dict[str, Any]) -> dict[str, Any] | None:
    """Recover complete article fields when only the trailing JSON string was cut off."""
    properties = schema.get("properties") or {}
    if not {"headline", "dek", "body"}.issubset(properties):
        return None
    headline = _json_string_field(content, "headline")
    dek = _json_string_field(content, "dek")
    body_match = re.search(r'"body"\s*:\s*\[', content)
    if not headline or not dek or not body_match:
        return None
    body_tail = content[body_match.end():]
    paragraphs = [
        str(json.loads(match.group(0)))
        for match in re.finditer(_JSON_STRING, body_tail)
    ]
    body_schema = properties.get("body") or {}
    minimum = int(body_schema.get("minItems") or 0)
    maximum = int(body_schema.get("maxItems") or len(paragraphs))
    if len(paragraphs) < minimum:
        return None
    return {"headline": headline, "dek": dek, "body": paragraphs[:maximum]}

class LLMProviderError(RuntimeError):
    """Base error raised by the configured local OpenAI-compatible provider."""


class LLMTransportError(LLMProviderError):
    """The provider could not be reached or returned an HTTP failure."""


class LLMSchemaError(LLMProviderError):
    """The provider response was not a JSON object matching the requested shape."""


class LLMRateLimitError(LLMTransportError):
    """The provider exhausted its bounded retries after HTTP 429 responses."""


def _response_text(response: Any) -> str:
    candidates = response.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return ""
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or [] if isinstance(content, dict) else []
    return "".join(
        str(part.get("text") or "")
        for part in parts
        if isinstance(part, dict)
    ).strip()


def _gemini_response_schema(value: Any) -> Any:
    """Keep constraints accepted by Gemini's structured-output schema subset."""
    if isinstance(value, dict):
        return {
            key: _gemini_response_schema(item)
            for key, item in value.items()
            if key not in {"minLength", "maxLength"}
        }
    if isinstance(value, list):
        return [_gemini_response_schema(item) for item in value]
    return value


class GeminiLLMClient:
    """Gemini JSON client with key rotation and bounded 429 backoff."""

    def __init__(
        self,
        *,
        api_keys: list[str] | None = None,
        model: str | None = None,
    ) -> None:
        configured = api_keys or [
            *str(settings.gemini_api_keys or "").split(","),
            str(settings.gemini_api_key or ""),
        ]
        self.api_keys = list(dict.fromkeys(key.strip() for key in configured if key.strip()))
        self.model = (model or settings.gemini_model).strip()

    def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        max_tokens: int,
        temperature: float,
        timeout: float,
        top_p: float | None = None,
    ) -> dict[str, Any]:
        if not self.api_keys:
            raise LLMProviderError("GEMINI_API_KEY or GEMINI_API_KEYS must be configured")
        safe_model = re.sub(r"[^A-Za-z0-9._-]", "", self.model)
        if not safe_model:
            raise LLMProviderError("GEMINI_MODEL must be configured")
        system = "\n".join(
            item["content"] for item in messages if item.get("role") == "system"
        )
        contents = [
            {
                "role": "model" if item.get("role") == "assistant" else "user",
                "parts": [{"text": str(item.get("content") or "")}],
            }
            for item in messages
            if item.get("role") != "system"
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": int(max_tokens),
                "temperature": float(temperature),
                "topP": float(top_p if top_p is not None else settings.llm_top_p),
                "responseMimeType": "application/json",
                "responseJsonSchema": _gemini_response_schema(schema),
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        attempts = max(1, int(settings.gemini_retry_attempts))
        last_error: BaseException | None = None
        for attempt in range(attempts):
            key = self.api_keys[attempt % len(self.api_keys)]
            request = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{safe_model}:generateContent",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "x-goog-api-key": key},
                method="POST",
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=max(1.0, min(float(timeout), settings.gemini_timeout_seconds)),
                ) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                content = _response_text(raw)
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise LLMSchemaError("Gemini response must be a JSON object")
                return parsed
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code != 429:
                    raise LLMTransportError(f"Gemini HTTP {exc.code}: {exc.reason}") from exc
                if attempt + 1 >= attempts:
                    break
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    delay = float(retry_after) if retry_after else 0.0
                except (TypeError, ValueError):
                    delay = 0.0
                if delay <= 0:
                    delay = settings.gemini_retry_base_seconds * (2 ** attempt)
                delay = min(delay, settings.gemini_retry_max_seconds)
                time.sleep(max(0.0, delay) + random.uniform(0.0, 0.35))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise LLMTransportError(str(exc) or type(exc).__name__) from exc
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
                raise LLMSchemaError("Gemini returned invalid article JSON") from exc
        raise LLMRateLimitError(
            f"Gemini remained rate-limited after {attempts} attempt(s)"
        ) from last_error


class LocalLLMClient:
    """Small OpenAI-compatible client for a loopback llama.cpp server."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        max_concurrency: int | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.model = model or settings.llm_model
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self._slots = (
            _generation_slots
            if max_concurrency is None
            else threading.BoundedSemaphore(max(1, int(max_concurrency)))
        )

    def generate_json(
        self,
        *,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        max_tokens: int,
        temperature: float,
        timeout: float,
        top_p: float | None = None,
    ) -> dict[str, Any]:
        if settings.llm_provider.lower() != "llamacpp":
            raise LLMProviderError(
                f"Unsupported SIGNAL_LLM_PROVIDER={settings.llm_provider!r}; expected 'llamacpp'"
            )
        if not self.base_url or not self.model:
            raise LLMProviderError("Local LLM base URL and model must be configured")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": float(temperature),
            "top_p": float(top_p if top_p is not None else settings.llm_top_p),
            "max_tokens": int(max_tokens),
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "schema": schema,
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with self._slots:
                with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
                    raw = json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LLMTransportError(str(exc) or type(exc).__name__) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMSchemaError("Local LLM returned invalid response JSON") from exc

        try:
            content = raw["choices"][0]["message"]["content"]
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except json.JSONDecodeError:
                    parsed = _recover_partial_article_object(content, schema)
                    if parsed is None:
                        raise
            else:
                parsed = content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMSchemaError("Local LLM response did not contain a JSON object") from exc
        if not isinstance(parsed, dict):
            raise LLMSchemaError("Local LLM response must be a JSON object")
        return parsed
