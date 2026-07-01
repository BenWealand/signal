from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class FilterMatch:
    blocked: bool
    term: str = ""
    source: str = ""


def _split_config(value: str) -> list[str]:
    parts = re.split(r"[\n,]", value or "")
    return [part.strip() for part in parts if part.strip()]


def blacklist_terms() -> list[str]:
    return _split_config(settings.prompt_blacklist)


def blacklist_patterns() -> list[str]:
    return _split_config(settings.prompt_blacklist_regex)


def text_for_article(article: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("prompt", "headline", "dek", "summary", "fallback_reason"):
        if article.get(key):
            parts.append(str(article[key]))
    body = article.get("body", [])
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            pass
    if isinstance(body, list):
        parts.extend(str(item) for item in body)
    else:
        parts.append(str(body))
    return "\n".join(parts)


def find_blacklist_match(text: str) -> FilterMatch:
    compact = re.sub(r"\s+", " ", text or "").lower()
    haystack = f" {compact} "
    for term in blacklist_terms():
        needle = term.lower()
        if not needle:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack):
            return FilterMatch(True, term=term, source="PROMPT_BLACKLIST")

    for pattern in blacklist_patterns():
        try:
            if re.search(pattern, text or "", flags=re.IGNORECASE):
                return FilterMatch(True, term=pattern, source="PROMPT_BLACKLIST_REGEX")
        except re.error:
            continue
    return FilterMatch(False)


def prompt_is_blocked(prompt: str) -> FilterMatch:
    return find_blacklist_match(prompt)


def article_is_blocked(article: dict[str, Any]) -> FilterMatch:
    return find_blacklist_match(text_for_article(article))
