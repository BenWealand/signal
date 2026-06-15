from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize_title(title: str) -> str:
    text = title.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def title_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalize_title(left), normalize_title(right)).ratio()


def probable_duplicate(candidate: dict[str, object], existing: dict[str, object]) -> bool:
    if candidate.get("url") and candidate.get("url") == existing.get("url"):
        return True
    if candidate.get("source_name") == existing.get("source_name"):
        return normalize_title(str(candidate.get("title", ""))) == normalize_title(str(existing.get("title", "")))
    return title_similarity(str(candidate.get("title", "")), str(existing.get("title", ""))) > 0.9

