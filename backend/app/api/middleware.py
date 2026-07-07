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
