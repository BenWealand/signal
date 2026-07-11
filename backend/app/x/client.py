from __future__ import annotations

"""
X API client — real search + post/reply.

Trends (`fetch_trending`) are intentionally not implemented; discovery falls
back to Signal desk topics and/or recent search seeded from those topics.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.config import settings
from app.x.models import XCandidate, XPostResult

logger = logging.getLogger(__name__)

_API_BASE = "https://api.x.com"
_USER_AGENT = "SignalDispatch/1.0 (+https://github.com/BenWealand/signal)"


class XApiNotConfigured(RuntimeError):
    """Raised when X credentials are missing or a feature is intentionally disabled."""


class XApiError(RuntimeError):
    """Raised when the X API returns an error response."""

    def __init__(self, message: str, *, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _percent_encode(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~")


def _oauth1_header(
    method: str,
    url: str,
    *,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
    extra_params: dict[str, str] | None = None,
) -> str:
    """Build an OAuth 1.0a Authorization header (HMAC-SHA1)."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    parsed = urllib.parse.urlparse(url)
    query_params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    all_params = {**query_params, **(extra_params or {}), **oauth_params}
    param_string = "&".join(
        f"{_percent_encode(k)}={_percent_encode(all_params[k])}"
        for k in sorted(all_params)
    )
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    base_string = "&".join(
        [
            method.upper(),
            _percent_encode(base_url),
            _percent_encode(param_string),
        ]
    )
    signing_key = f"{_percent_encode(consumer_secret)}&{_percent_encode(access_token_secret)}"
    digest = hmac.new(
        signing_key.encode("utf-8"),
        base_string.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode("utf-8")
    header_value = ", ".join(
        f'{_percent_encode(k)}="{_percent_encode(oauth_params[k])}"'
        for k in sorted(oauth_params)
    )
    return f"OAuth {header_value}"


def _truncate(text: str, max_chars: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 1)].rstrip() + "…"


class XClient:
    """
    X API adapter.

    Credentials (Render env):
      X_API_BEARER_TOKEN                         — recent search (app-only)
      X_API_KEY / X_API_SECRET                   — OAuth 1.0a consumer
      X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET     — OAuth 1.0a user (posting)
      X_TRENDS_WOEID                             — unused while trends are off
    """

    def __init__(self) -> None:
        self.bearer_token = (settings.x_api_bearer_token or "").strip()
        self.api_key = (settings.x_api_key or "").strip()
        self.api_secret = (settings.x_api_secret or "").strip()
        self.access_token = (settings.x_access_token or "").strip()
        self.access_token_secret = (settings.x_access_token_secret or "").strip()
        self.woeid = int(settings.x_trends_woeid or 1)

    def read_configured(self) -> bool:
        return bool(self.bearer_token or (self.api_key and self.api_secret and self.access_token and self.access_token_secret))

    def write_configured(self) -> bool:
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
            "implemented": {
                "search": True,
                "post": True,
                "reply": True,
                "lookup": True,
                "trends": False,
            },
        }

    # ── HTTP helpers ─────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: str = "bearer",
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        query = {k: str(v) for k, v in (query or {}).items() if v is not None and v != ""}
        url = f"{_API_BASE}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"

        headers = {
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        data: bytes | None = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if auth == "bearer":
            if not self.bearer_token:
                raise XApiNotConfigured("X_API_BEARER_TOKEN is required for this request")
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        elif auth == "oauth1":
            if not self.write_configured():
                raise XApiNotConfigured(
                    "X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, and X_ACCESS_TOKEN_SECRET "
                    "are required for posting"
                )
            headers["Authorization"] = _oauth1_header(
                method,
                url,
                consumer_key=self.api_key,
                consumer_secret=self.api_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
            )
        else:
            raise ValueError(f"Unknown auth mode: {auth}")

        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                if not raw.strip():
                    return {}
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            detail = raw
            try:
                parsed = json.loads(raw)
                detail = (
                    parsed.get("detail")
                    or parsed.get("title")
                    or (parsed.get("errors") or [{}])[0].get("message")
                    or raw
                )
            except Exception:
                pass
            raise XApiError(
                f"X API {method.upper()} {path} failed ({exc.code}): {detail}",
                status=int(exc.code or 0),
                body=raw,
            ) from exc
        except urllib.error.URLError as exc:
            raise XApiError(f"X API network error: {exc.reason}") from exc

    # ── Trends (intentionally not implemented) ───────────────────────────────

    def fetch_trending(self, *, limit: int = 10, woeid: int | None = None) -> list[XCandidate]:
        """
        Trends are intentionally disabled.

        Use Signal desk topics + ``search_recent`` instead (see pipeline discovery).
        """
        raise XApiNotConfigured(
            "X trends are not enabled in Signal. "
            "Discovery uses Signal desk topics and recent search instead."
        )

    # ── Search / lookup ──────────────────────────────────────────────────────

    def search_recent(self, query: str, *, limit: int = 10) -> list[XCandidate]:
        """
        Recent search (last 7 days) via GET /2/tweets/search/recent.
        Requires X_API_BEARER_TOKEN (or falls back to OAuth1 if bearer missing).
        """
        cleaned = (query or "").strip()
        if not cleaned:
            return []
        if not self.bearer_token and not self.write_configured():
            raise XApiNotConfigured(
                "X read credentials missing. Set X_API_BEARER_TOKEN for search."
            )

        # Prefer English, exclude retweets/replies for cleaner news signals.
        search_query = cleaned
        if "is:retweet" not in cleaned.lower():
            search_query = f"({cleaned}) -is:retweet -is:reply lang:en"

        max_results = max(10, min(int(limit or 10), 100))
        auth = "bearer" if self.bearer_token else "oauth1"
        payload = self._request(
            "GET",
            "/2/tweets/search/recent",
            query={
                "query": search_query,
                "max_results": str(max_results),
                "tweet.fields": "created_at,lang,author_id,public_metrics",
                "expansions": "author_id",
                "user.fields": "username,name",
            },
            auth=auth,
            timeout=20.0,
        )
        return self._candidates_from_search_payload(payload, topic=cleaned)[: max(1, int(limit or 10))]

    def lookup_post(self, post_id: str) -> XCandidate | None:
        """Lookup a single post by id via GET /2/tweets/:id."""
        pid = (post_id or "").strip()
        if not pid:
            return None
        if not self.bearer_token and not self.write_configured():
            raise XApiNotConfigured("X credentials missing for tweet lookup")

        auth = "bearer" if self.bearer_token else "oauth1"
        payload = self._request(
            "GET",
            f"/2/tweets/{urllib.parse.quote(pid)}",
            query={
                "tweet.fields": "created_at,lang,author_id,public_metrics",
                "expansions": "author_id",
                "user.fields": "username,name",
            },
            auth=auth,
            timeout=15.0,
        )
        rows = self._candidates_from_search_payload(
            {
                "data": [payload.get("data")] if payload.get("data") else [],
                "includes": payload.get("includes") or {},
            },
            topic="",
        )
        return rows[0] if rows else None

    def candidate_from_url(self, url: str) -> XCandidate | None:
        """Extract status id from an x.com/twitter.com URL and look it up."""
        post_id = _status_id_from_url(url)
        if not post_id:
            return None
        return self.lookup_post(post_id)

    def _candidates_from_search_payload(self, payload: dict[str, Any], *, topic: str) -> list[XCandidate]:
        users = {
            str(u.get("id")): u
            for u in ((payload.get("includes") or {}).get("users") or [])
            if u.get("id")
        }
        out: list[XCandidate] = []
        for row in payload.get("data") or []:
            if not isinstance(row, dict):
                continue
            post_id = str(row.get("id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not post_id or not text:
                continue
            author = users.get(str(row.get("author_id") or ""), {}) or {}
            handle = str(author.get("username") or "").strip()
            metrics = row.get("public_metrics") or {}
            score = float(
                (metrics.get("like_count") or 0)
                + 2 * (metrics.get("repost_count") or metrics.get("retweet_count") or 0)
                + (metrics.get("reply_count") or 0)
            )
            trend_url = (
                f"https://x.com/{handle}/status/{post_id}"
                if handle
                else f"https://x.com/i/web/status/{post_id}"
            )
            out.append(
                XCandidate(
                    topic=topic or _truncate(text, 80),
                    snippet=_truncate(text, 280),
                    prompt=topic or _truncate(text, 120),
                    trend_url=trend_url,
                    post_id=post_id,
                    author_handle=handle,
                    source="x-api",
                    tag="x-trend",
                    score=score,
                    provider="x-api-search",
                )
            )
        out.sort(key=lambda c: c.score, reverse=True)
        return out

    # ── Post / reply ─────────────────────────────────────────────────────────

    def post_tweet(
        self,
        text: str,
        *,
        in_reply_to_id: str | None = None,
        dry_run: bool | None = None,
    ) -> XPostResult:
        """
        Create a post (or reply) via POST /2/tweets with OAuth 1.0a user context.
        """
        body = (text or "").strip()
        if not body:
            return XPostResult(ok=False, dry_run=True, message="Empty post text", provider="x-api")

        use_dry_run = settings.x_dry_run if dry_run is None else bool(dry_run)
        if use_dry_run:
            return XPostResult(
                ok=True,
                dry_run=True,
                posted=False,
                message="Dry run — post not sent to X. Set SIGNAL_X_DRY_RUN=false to publish.",
                provider="x-api",
            )

        if not self.write_configured():
            return XPostResult(
                ok=False,
                dry_run=False,
                posted=False,
                message=(
                    "X write credentials missing. Set X_API_KEY, X_API_SECRET, "
                    "X_ACCESS_TOKEN, and X_ACCESS_TOKEN_SECRET."
                ),
                provider="x-api",
            )

        payload: dict[str, Any] = {"text": body[:280]}
        reply_id = (in_reply_to_id or "").strip()
        if reply_id:
            payload["reply"] = {"in_reply_to_tweet_id": reply_id}

        try:
            response = self._request(
                "POST",
                "/2/tweets",
                json_body=payload,
                auth="oauth1",
                timeout=20.0,
            )
        except XApiError as exc:
            logger.warning("X post failed: %s", exc)
            return XPostResult(
                ok=False,
                dry_run=False,
                posted=False,
                message=str(exc),
                provider="x-api",
            )
        except XApiNotConfigured as exc:
            return XPostResult(
                ok=False,
                dry_run=False,
                posted=False,
                message=str(exc),
                provider="x-api",
            )

        data = response.get("data") or {}
        post_id = str(data.get("id") or "").strip()
        post_url = f"https://x.com/i/web/status/{post_id}" if post_id else ""
        return XPostResult(
            ok=bool(post_id),
            dry_run=False,
            posted=bool(post_id),
            post_id=post_id,
            post_url=post_url,
            message="Posted to X" if post_id else "X API returned no post id",
            provider="x-api",
        )

    def reply_to_post(self, post_id: str, text: str, *, dry_run: bool | None = None) -> XPostResult:
        return self.post_tweet(text, in_reply_to_id=(post_id or "").strip() or None, dry_run=dry_run)


def _status_id_from_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw)
    except Exception:
        return ""
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host not in {"x.com", "twitter.com", "mobile.twitter.com"}:
        return ""
    parts = [p for p in (parsed.path or "").split("/") if p]
    # /{user}/status/{id} or /i/web/status/{id}
    if len(parts) >= 3 and parts[-2].lower() == "status" and parts[-1].isdigit():
        return parts[-1]
    if len(parts) >= 1 and parts[-1].isdigit():
        return parts[-1]
    return ""


_client: XClient | None = None


def get_x_client() -> XClient:
    global _client
    if _client is None:
        _client = XClient()
    return _client


def reset_x_client() -> None:
    """Test helper to clear the singleton."""
    global _client
    _client = None
