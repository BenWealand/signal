from __future__ import annotations

import copy
import re
import time
import urllib.parse
from typing import Any

from app.config import settings
from app.ingest.source_registry import domain_from_url
from app.llm.provider import (
    GeminiLLMClient,
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
    min_text_chars: int = 80,
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
        if len(text) < min_text_chars:
            continue
        excerpt = text[: min(per_source_chars, remaining)].rstrip()
        if len(excerpt) < min_text_chars:
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


def _validate_package(package: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    if set(package) != {"headline", "dek", "body"}:
        raise LLMSchemaError("Article package contained missing or extra keys")
    headline = _plain_article_text(package.get("headline")).strip()
    dek = _plain_article_text(package.get("dek")).strip()
    body = package.get("body")
    if not headline or len(headline) > 160:
        raise LLMSchemaError("Article headline failed schema validation")
    if not dek or len(dek) > 280:
        raise LLMSchemaError("Article dek failed schema validation")
    body_schema = (schema.get("properties") or {}).get("body") or {}
    minimum = int(body_schema.get("minItems") or 3)
    maximum = int(body_schema.get("maxItems") or 8)
    paragraph_schema = body_schema.get("items") or {}
    min_length = int(paragraph_schema.get("minLength") or 80)
    max_length = int(paragraph_schema.get("maxLength") or 1800)
    if not isinstance(body, list) or not minimum <= len(body) <= maximum:
        raise LLMSchemaError("Article body failed paragraph-count validation")
    paragraphs = [_plain_article_text(item).strip() for item in body]
    if any(not min_length <= len(item) <= max_length for item in paragraphs):
        raise LLMSchemaError("Article paragraph failed length validation")
    return {"headline": headline, "dek": dek, "body": paragraphs}


def _plain_article_text(value: Any) -> str:
    """Remove lightweight Markdown the model may emit despite instructions."""
    text = str(value or "")
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}(?:#{1,6}\s+|[-*+]\s+)", "", text)
    return text


def generate_article_package(
    prompt: str,
    source_articles: list[dict[str, Any]],
    *,
    mode: str = "thorough",
    source_policy: str = "standard",
    client: LocalLLMClient | GeminiLLMClient | None = None,
) -> dict[str, Any]:
    x_response = source_policy == "x_response"
    section_fast = source_policy == "section_fast"
    fast_mode = mode == "fast"
    required_sources = 1 if x_response else (2 if fast_mode else 4)
    # Preserve the richer pre-local-model website contract. Only X responses
    # use the compact prompt designed for four-core local inference.
    website_fast = fast_mode and not x_response
    sources = prepare_sources(
        source_articles,
        min_sources=required_sources,
        max_sources=4 if x_response else 6,
        per_source_chars=750 if x_response else (900 if website_fast else 1300),
        total_chars=3200 if x_response else (5500 if website_fast else 9000),
        min_text_chars=20 if x_response else (60 if section_fast else 80),
    )
    if len(sources) < required_sources:
        if x_response:
            raise LLMSchemaError("At least one usable originating X post is required for generation")
        if fast_mode:
            raise LLMSchemaError("At least two independent usable sources are required for fast generation")
        raise LLMSchemaError("At least four independent usable sources are required for generation")
    paragraph_target = (
        "3-4 concise"
        if x_response
        else ("4-6 substantive" if fast_mode else "6-8 substantive")
    )
    source_block = "\n\n".join(
        f"SOURCE {index}\nOutlet: {source['source_name']}\nTitle: {source['title']}\n"
        f"URL: {source['url']}\nExcerpt: {source['text']}"
        for index, source in enumerate(sources, start=1)
    )
    evidence_instruction = (
        "This is an X-response article based on limited source material. Attribute the originating "
        "post explicitly, do not imply independent corroboration, and label unknown details as unverified."
        if x_response
        else (
            "This fast section article has limited source coverage. Attribute material claims, avoid claiming "
            "broad consensus, and make any uncertainty or disagreement explicit."
            if section_fast
            else "Lead with the strongest corroborated development and make uncertainty visible."
        )
    )
    messages = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {
            "role": "user",
            "content": (
                f"Reader topic: {prompt}\n\nWrite a sourced article of {paragraph_target} paragraphs. "
                f"{evidence_instruction}\n\n"
                f"{source_block}"
            ),
        },
    ]
    max_tokens = (
        min(
            settings.llm_fast_max_tokens if fast_mode else settings.llm_thorough_max_tokens,
            settings.llm_emergency_max_tokens,
        )
        if x_response
        else (
            settings.gemini_fast_max_tokens
            if fast_mode
            else settings.gemini_thorough_max_tokens
        )
    )
    response_schema = copy.deepcopy(ARTICLE_SCHEMA)
    if x_response:
        response_schema["properties"]["body"]["maxItems"] = 4
        response_schema["properties"]["body"]["items"]["maxLength"] = 800
    elif fast_mode:
        response_schema["properties"]["body"]["minItems"] = 4
        response_schema["properties"]["body"]["maxItems"] = 6
        response_schema["properties"]["body"]["items"]["maxLength"] = 1800
    else:
        response_schema["properties"]["body"]["minItems"] = 6
        response_schema["properties"]["body"]["maxItems"] = 8
        response_schema["properties"]["body"]["items"]["maxLength"] = 1800
    # Website and section work use Gemini. X-response work remains on the
    # loopback Ministral writer so external quota never blocks auto-posting.
    if client is not None:
        active_client = client
    elif x_response:
        active_client = LocalLLMClient()
    elif section_fast:
        active_client = GeminiLLMClient(
            api_keys=[settings.daily_gemini_api_key],
            credential_label="DAILY_GEMINI_API_KEY",
        )
    else:
        active_client = GeminiLLMClient(
            api_keys=[
                settings.demand_gemini_api_key,
                settings.fallback_gemini_api_key,
            ],
            credential_label="DEMAND_GEMINI_API_KEY/FALLBACK_GEMINI_API_KEY",
        )
    last_error: BaseException | None = None
    # Exactly one retry, limited to transport or schema failures.
    for attempt in range(2):
        try:
            return _validate_package(
                active_client.generate_json(
                    messages=messages,
                    schema=response_schema,
                    max_tokens=max_tokens,
                    temperature=settings.llm_temperature,
                    top_p=settings.llm_top_p,
                    timeout=settings.llm_timeout_seconds,
                ),
                response_schema,
            )
        except (LLMTransportError, LLMSchemaError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.15)
                continue
            raise
    raise LLMSchemaError(str(last_error) if last_error else "Article generation failed")
