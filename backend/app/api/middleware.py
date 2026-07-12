from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_FEED_CACHE_PATHS = {
    "/generated-articles",
    "/stories",
    "/stories/latest",
    "/stories/trending",
    "/news/trending",
    "/news/trending-topics",
    "/feeds/bootstrap",
}


class FeedCacheHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.method != "GET":
            return response

        path = request.url.path.rstrip("/") or "/"
        if path in _FEED_CACHE_PATHS or path.startswith("/news/"):
            response.headers.setdefault("Cache-Control", "public, max-age=60, stale-while-revalidate=300")
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline browser/API hardening headers on every response."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # API responses are not meant to be cached by shared proxies when authenticated.
        if request.url.path.startswith(("/users", "/admin")):
            response.headers.setdefault("Cache-Control", "no-store")
        return response