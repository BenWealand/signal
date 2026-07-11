from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class XCandidate:
    """Normalized topic/post Signal can turn into an article."""

    topic: str
    snippet: str = ""
    prompt: str = ""
    trend_url: str = ""
    post_id: str = ""
    author_handle: str = ""
    source: str = "x-agent"
    tag: str = "x-trend"
    score: float = 0.0
    provider: str = "manual"  # x-api | signal-internal | manual

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class XPostResult:
    """Result of attempting to publish on X."""

    ok: bool
    dry_run: bool = True
    posted: bool = False
    post_id: str = ""
    post_url: str = ""
    message: str = ""
    provider: str = "stub"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class XSharePackage:
    """Everything needed to keep an article on the frontend and share it."""

    status: str
    article_url: str
    reply_text: str
    trend_url: str = ""
    candidate: dict[str, Any] = field(default_factory=dict)
    article: dict[str, Any] = field(default_factory=dict)
    share: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
