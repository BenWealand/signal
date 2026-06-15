from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Article:
    source_name: str
    title: str
    url: str
    published_at: str
    raw_text: str
    language: str = "en"
    status: str = "new"

