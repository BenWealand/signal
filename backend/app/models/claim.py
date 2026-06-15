from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Claim:
    text: str
    confidence_score: float = 0.75

