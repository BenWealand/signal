from __future__ import annotations

import re
import time
import urllib.parse
from typing import Any

from app.config import settings
from app.ingest.source_registry import domain_from_url
from app.llm.provider import (
    LLMSchemaError,
    LLMTransportError,
    LocalLLMClient,
)


ARTICLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "maxLength": 160},
        "dek": {"type": "string", "maxLength": 280},
        "body": {
            "type": "array",
            "minItems": 3,
            "maxItems": 7,
            "items": {
                "type": "string",
                "minLength": 80,
                "maxLength": 1200,
            },
        },
    },
    "required": ["headline", "dek", "body"],
    "additionalProperties": False,
}

SYSTEM_MESSAGE = """You are Signal's neutral news writer.
Write only from the supplied source material. Reconcile differences explicitly,
attribute claims when support is limited, and never invent facts, quotations, or
context. Return exactly the requested JSON object. Do not use Markdown."""


def _canonical_url(value: str) -> str:
    try:
        parsed = urllib.parse.urlsplit((value or "").strip())
    except ValueError:
        return ""
    if not parsed.netloc:
        return ""
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    query = [
        (key, val)
        for key, val in query
        if not key.lower().startswith("utm_")
        and key.lower() not in {"gclid", "fbclid", "ref", "source"}
    ]
    return urllib.parse.urlunsplit(
        (parsed.scheme.lower() or "https", parsed.netloc.lower(), parsed.path.rstrip("/"), urllib.parse.urlencode(query), "")
    )


def prepare_sources(
    source_articles: list[dict[str, Any]],
    *,
    min_sources: int = 4,
    max_sources: int = 6,
    per_source_chars: int = 1300,
    total_chars: int = 8500,
) -> list[dict[str, str]]:
    """Choose rich, independent source excerpts with bounded prompt size."""
    ranked = sorted(
        source_articles,
        key=lambda item: len(
            str(item.get("clean_text") or item.get("raw_text") or item.get("description") or "")
        ),
        reverse=True,
    )
    chosen: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    seen_domains: set[str] = set()
    remaining = max(1000, int(total_chars))
    for item in ranked:
        url = _canonical_url(str(item.get("url") or ""))
        domain = domain_from_url(url) or str(item.get("domain") or "").lower()
        if not url or url in seen_urls or (domain and domain in seen_domains):
            continue
        text = re.sub(
            r"\s+",
            " ",
            str(item.get("clean_text") or item.get("raw_text") or item.get("description") or ""),
        ).strip()
        if len(text) < 80:
            continue
        excerpt = text[: min(per_source_chars, remaining)].rstrip()
        if len(excerpt) < 80:
            break
        chosen.append(
            {
                "source_name": str(item.get("source_name") or domain or "Public source").strip(),
                "title": str(item.get("title") or "").strip()[:240],
                "url": url,
                "text": excerpt,
            }
        )
        seen_urls.add(url)
        if domain:
            seen_domains.add(domain)
        remaining -= len(excerpt)
        if len(chosen) >= max_sources or remaining < 80:
            break

    return chosen[:max_sources]


def _validate_package(package: dict[str, Any]) -> dict[str, Any]:
    if set(package) != {"headline", "dek", "body"}:
        raise LLMSchemaError("Article package contained missing or extra keys")
    headline = str(package.get("headline") or "").strip()
    dek = str(package.get("dek") or "").strip()
    body = package.get("body")
    if not headline or len(headline) > 160:
        raise LLMSchemaError("Article headline failed schema validation")
    if not dek or len(dek) > 280:
        raise LLMSchemaError("Article dek failed schema validation")
    if not isinstance(body, list) or not 3 <= len(body) <= 7:
        raise LLMSchemaError("Article body failed paragraph-count validation")
    paragraphs = [str(item).strip() for item in body]
    if any(not 80 <= len(item) <= 1200 for item in paragraphs):
        raise LLMSchemaError("Article paragraph failed length validation")
    return {"headline": headline, "dek": dek, "body": paragraphs}


def generate_article_package(
    prompt: str,
    source_articles: list[dict[str, Any]],
    *,
    mode: str = "thorough",
    client: LocalLLMClient | None = None,
) -> dict[str, Any]:
    sources = prepare_sources(source_articles)
    if len(sources) < 4:
        raise LLMSchemaError("At least four independent usable sources are required for generation")
    paragraph_target = "4-5" if mode == "fast" else "6-7"
    source_block = "\n\n".join(
        f"SOURCE {index}\nOutlet: {source['source_name']}\nTitle: {source['title']}\n"
        f"URL: {source['url']}\nExcerpt: {source['text']}"
        for index, source in enumerate(sources, start=1)
    )
    messages = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {
            "role": "user",
            "content": (
                f"Reader topic: {prompt}\n\nWrite a sourced article of {paragraph_target} paragraphs. "
                "Lead with the strongest corroborated development and make uncertainty visible.\n\n"
                f"{source_block}"
            ),
        },
    ]
    max_tokens = min(
        settings.llm_fast_max_tokens
        if mode == "fast"
        else settings.llm_thorough_max_tokens,
        settings.llm_emergency_max_tokens,
    )
    active_client = client or LocalLLMClient()
    last_error: BaseException | None = None
    # Exactly one retry, limited to transport or schema failures.
    for attempt in range(2):
        try:
            return _validate_package(
                active_client.generate_json(
                    messages=messages,
                    schema=ARTICLE_SCHEMA,
                    max_tokens=max_tokens,
                    temperature=settings.llm_temperature,
                    top_p=settings.llm_top_p,
                    timeout=settings.llm_timeout_seconds,
                )
            )
        except (LLMTransportError, LLMSchemaError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.15)
                continue
            raise
    raise LLMSchemaError(str(last_error) if last_error else "Article generation failed")
