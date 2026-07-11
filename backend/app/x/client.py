from __future__ import annotations

"""
X API client boundary.

Fill in the method bodies marked IMPLEMENT when you wire X API credentials.
Until then, methods raise ``XApiNotConfigured`` so the pipeline can fall back
to Signal-internal trending topics and dry-run shares.
"""

import logging
from typing import Any

from app.config import settings
from app.x.models import XCandidate, XPostResult

logger = logging.getLogger(__name__)


class XApiNotConfigured(RuntimeError):
    """Raised when X credentials are missing or the API body is not implemented."""


class XClient:
    """
    Thin adapter around the X API.

    Expected credentials (set on Render / local `.env`):
      X_API_BEARER_TOKEN      — app-only bearer for trends/search
      X_API_KEY / X_API_SECRET — OAuth 1.0a consumer (posting)
      X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET — user access tokens (posting)
      X_TRENDS_WOEID          — Yahoo WOEID for trends (1 = worldwide)
    """

    def __init__(self) -> None:
        self.bearer_token = (settings.x_api_bearer_token or "").strip()
        self.api_key = (settings.x_api_key or "").strip()
        self.api_secret = (settings.x_api_secret or "").strip()
        self.access_token = (settings.x_access_token or "").strip()
        self.access_token_secret = (settings.x_access_token_secret or "").strip()
        self.woeid = int(settings.x_trends_woeid or 1)

    def read_configured(self) -> bool:
        """True when enough credentials exist to call read endpoints."""
        return bool(self.bearer_token or (self.api_key and self.api_secret))

    def write_configured(self) -> bool:
        """True when enough credentials exist to post/reply."""
        return bool(
            self.api_key
            and self.api_secret
            and self.access_token
            and self.access_token_secret
        )

    def status(self) -> dict[str, Any]:
        return {
            "readConfigured": self.read_configured(),
            "writeConfigured": self.write_configured(),
            "trendsWoeid": self.woeid,
            "autoPost": bool(settings.x_auto_post),
            "dryRunDefault": bool(settings.x_dry_run),
            "implemented": False,  # flip to True once API bodies are filled in
        }

    # ── Read APIs (IMPLEMENT) ────────────────────────────────────────────────

    def fetch_trending(self, *, limit: int = 10, woeid: int | None = None) -> list[XCandidate]:
        """
        IMPLEMENT: call X trends endpoint and map into ``XCandidate`` rows.

        Suggested X API:
          GET https://api.twitter.com/1.1/trends/place.json?id={woeid}
          Authorization: Bearer {X_API_BEARER_TOKEN}

        Return candidates with at least ``topic`` set. Prefer including a short
        ``snippet`` (promoted content name / tweet volume note) when available.
        """
        if not self.read_configured():
            raise XApiNotConfigured(
                "X read credentials missing. Set X_API_BEARER_TOKEN "
                "(or X_API_KEY + X_API_SECRET) then implement fetch_trending()."
            )
        raise XApiNotConfigured(
            "fetch_trending() is not implemented yet. "
            "Wire the X trends API in app/x/client.py and return XCandidate rows."
        )

    def search_recent(self, query: str, *, limit: int = 10) -> list[XCandidate]:
        """
        IMPLEMENT: recent search for public posts matching ``query``.

        Suggested X API v2:
          GET https://api.x.com/2/tweets/search/recent?query=...&max_results=...
          Authorization: Bearer {X_API_BEARER_TOKEN}

        Map each hit to XCandidate(topic=query, snippet=text, trend_url=..., post_id=...).
        """
        cleaned = (query or "").strip()
        if not cleaned:
            return []
        if not self.read_configured():
            raise XApiNotConfigured(
                "X read credentials missing. Set X_API_BEARER_TOKEN then implement search_recent()."
            )
        raise XApiNotConfigured(
            "search_recent() is not implemented yet. "
            "Wire X recent search in app/x/client.py."
        )

    # ── Write APIs (IMPLEMENT) ───────────────────────────────────────────────

    def post_tweet(
        self,
        text: str,
        *,
        in_reply_to_id: str | None = None,
        dry_run: bool | None = None,
    ) -> XPostResult:
        """
        IMPLEMENT: create a tweet or reply.

        Suggested X API v2:
          POST https://api.x.com/2/tweets
          OAuth 1.0a user context with X_API_KEY / SECRET + ACCESS_TOKEN / SECRET
          Body: {"text": "...", "reply": {"in_reply_to_tweet_id": "..."}}

        When ``dry_run`` is True (default via SIGNAL_X_DRY_RUN), do not call X —
        return a simulated success so the rest of the pipeline can be tested.
        """
        body = (text or "").strip()
        if not body:
            return XPostResult(ok=False, dry_run=True, message="Empty post text")

        use_dry_run = settings.x_dry_run if dry_run is None else bool(dry_run)
        if use_dry_run:
            return XPostResult(
                ok=True,
                dry_run=True,
                posted=False,
                message="Dry run — post not sent to X. Set SIGNAL_X_DRY_RUN=false after implementing post_tweet().",
                provider="stub",
            )

        if not self.write_configured():
            return XPostResult(
                ok=False,
                dry_run=False,
                posted=False,
                message=(
                    "X write credentials missing. Set X_API_KEY, X_API_SECRET, "
                    "X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET then implement post_tweet()."
                ),
                provider="stub",
            )

        raise XApiNotConfigured(
            "post_tweet() is not implemented yet. "
            "Wire X tweet create in app/x/client.py."
        )

    def reply_to_post(self, post_id: str, text: str, *, dry_run: bool | None = None) -> XPostResult:
        """Convenience wrapper for replies. IMPLEMENT via post_tweet."""
        return self.post_tweet(text, in_reply_to_id=(post_id or "").strip() or None, dry_run=dry_run)


_client: XClient | None = None


def get_x_client() -> XClient:
    global _client
    if _client is None:
        _client = XClient()
    return _client
