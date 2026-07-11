from __future__ import annotations

import re

from app.policy.prompt_filter import prompt_is_blocked
from app.x.models import XCandidate

_VAGUE = re.compile(
    r"^(this is (wild|crazy|insane)|wow+|lol+|lmao+|om+g+|thoughts\??|so true)$",
    re.I,
)
_HAS_SIGNAL = re.compile(
    r"[A-Za-z]{3,}.*(vote|bill|court|election|market|strike|war|deal|ceo|policy|"
    r"storm|quake|trial|verdict|budget|tariff|layoff|merger|launch|protest|"
    r"climate|vaccine|congress|senate|president|minister|governor)",
    re.I,
)
_ENTITYISH = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}|#[A-Za-z][A-Za-z0-9_]{2,})\b")


def candidate_text(candidate: XCandidate) -> str:
    parts = [candidate.prompt, candidate.topic, candidate.snippet]
    return " ".join(p for p in parts if p).strip()


def is_actionable_candidate(candidate: XCandidate) -> tuple[bool, str]:
    """
    Decide whether a trend/post is worth writing an article about.

    Returns (ok, reason). ok=False means skip.
    """
    text = candidate_text(candidate)
    if len(text) < 8:
        return False, "too_short"
    if _VAGUE.match(text.strip()):
        return False, "vague_reaction"
    blocked = prompt_is_blocked(text)
    if blocked.blocked:
        return False, f"blocked:{blocked.source}"
    # Prefer named entities / hashtags or newsy keywords.
    if _ENTITYISH.search(text) or _HAS_SIGNAL.search(text) or text.startswith("#"):
        return True, "ok"
    # Allow longer free-text topics that look like news queries.
    if len(text.split()) >= 4:
        return True, "ok"
    return False, "weak_topic"


def filter_candidates(candidates: list[XCandidate], *, limit: int = 5) -> list[XCandidate]:
    kept: list[XCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        ok, _reason = is_actionable_candidate(candidate)
        if not ok:
            continue
        key = re.sub(r"\s+", " ", candidate_text(candidate).lower())[:160]
        if key in seen:
            continue
        seen.add(key)
        kept.append(candidate)
        if len(kept) >= max(1, limit):
            break
    return kept
