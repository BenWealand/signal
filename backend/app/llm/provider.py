from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

from app.config import settings

_generation_slots = threading.BoundedSemaphore(max(1, settings.llm_max_concurrency))

class LLMProviderError(RuntimeError):
    """Base error raised by the configured local OpenAI-compatible provider."""


class LLMTransportError(LLMProviderError):
    """The provider could not be reached or returned an HTTP failure."""


class LLMSchemaError(LLMProviderError):
    """The provider response was not a JSON object matching the requested shape."""


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
                "type": "json_object",
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
            parsed = json.loads(content) if isinstance(content, str) else content
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMSchemaError("Local LLM response did not contain a JSON object") from exc
        if not isinstance(parsed, dict):
            raise LLMSchemaError("Local LLM response must be a JSON object")
        return parsed
