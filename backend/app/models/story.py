from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Story:
    id: int
    topic_label: str
    summary_text: str = ""

