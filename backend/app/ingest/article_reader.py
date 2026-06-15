from __future__ import annotations

import html
import re
import urllib.request
import urllib.parse
import base64
from html.parser import HTMLParser

try:
    import trafilatura
    _HAS_TRAFILATURA = True
except ImportError:
    _HAS_TRAFILATURA = False

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Google News URL unwrapping ────────────────────────────────────────────────
_GN_RSS_PREFIX = "https://news.google.com/rss/articles/"
_GN_NEWS_PREFIX = "https://news.google.com/news/url"
_BING_CLICK_HOST = "bing.com/news/apiclick"


def _unwrap_google_news_url(url: str) -> str:
    """
    Attempt to extract the real publisher URL from a Google News redirect URL.

    Google News RSS links look like:
      https://news.google.com/rss/articles/CBMiXmh0dHBzOi8v...
    The base64 payload after 'CBMi' encodes the real URL.

    Returns the decoded URL if successful, otherwise returns the original.
    """
    if not url.startswith(_GN_RSS_PREFIX):
        # Handle older /news/url?url=... style
        if "news.google.com" in url:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query)
            for key in ("url", "q"):
                real = qs.get(key, [None])[0]
                if real and real.startswith("http"):
                    return real
        return url

    try:
        # Strip the prefix to get the encoded payload
        encoded = url[len(_GN_RSS_PREFIX):]
        # Remove any query string
        encoded = encoded.split("?")[0]
        # Google encodes URLs as: CBMi + base64url(real_url)
        # The 'CBMi' prefix is a protobuf header; skip first 2 bytes after decode
        # Pad to multiple of 4 for valid base64
        padded = encoded + "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode(padded)
        # Find the start of the URL (look for http)
        http_pos = raw.find(b"http")
        if http_pos != -1:
            # Read until first null byte or non-printable char
            end = http_pos
            while end < len(raw) and 32 <= raw[end] < 127:
                end += 1
            decoded_url = raw[http_pos:end].decode("ascii", errors="ignore").rstrip("?&#")
            if decoded_url.startswith("http"):
                return decoded_url
    except Exception:
        pass
    return url


# ── Fallback HTML parser (used when trafilatura is not installed) ─────────────

class _ArticleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._capture_tag: str | None = None
        self._buffer: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "form", "aside"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"p", "h1", "h2", "h3", "li"}:
            self._capture_tag = tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "nav", "header", "footer", "form", "aside"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == self._capture_tag:
            text = _normalize_text(" ".join(self._buffer))
            if _looks_like_article_text(text):
                self.blocks.append(text)
            self._capture_tag = None
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._capture_tag is None:
            return
        self._buffer.append(data)


def _normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _looks_like_article_text(text: str) -> bool:
    if len(text) < 45:
        return False
    junk = ("cookie", "subscribe", "sign up", "advertisement", "all rights reserved",
            "privacy policy", "terms of service", "javascript is required")
    return not any(marker in text.lower() for marker in junk)


def _extract_with_fallback_parser(raw_html: str) -> str:
    parser = _ArticleTextParser()
    try:
        parser.feed(raw_html)
    except Exception:
        return ""
    return " ".join(parser.blocks[:30])


# ── Main public API ───────────────────────────────────────────────────────────

def unwrap_bing_news_url(url: str) -> str:
    """
    Bing News RSS links use click-tracker URLs:
      http://www.bing.com/news/apiclick.aspx?...&url=https%3A%2F%2Fpublisher.com%2F...
    Extract the real publisher URL from the `url=` query parameter.
    """
    if _BING_CLICK_HOST not in url:
        return url
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        real = qs.get("url", [None])[0]
        if real and real.startswith("http"):
            return real
    except Exception:
        pass
    return url


def fetch_raw_html(url: str, timeout: int = 14) -> str:
    """
    Download HTML for a URL. Returns empty string on any error.

    For Google News redirect URLs, the real publisher URL is decoded first
    so trafilatura fetches the actual article, not a Google landing page.
    """
    if not url:
        return ""

    # Unwrap Google News redirect URLs before fetching
    if "news.google.com" in url:
        url = _unwrap_google_news_url(url)

    # Prefer trafilatura.fetch_url — better browser headers, redirect handling,
    # and specifically tested against news sites.
    if _HAS_TRAFILATURA:
        try:
            result = trafilatura.fetch_url(url)
            if result and len(result) > 200:
                return result
        except Exception:
            pass

    # Fallback: plain urllib
    request = urllib.request.Request(url, headers=_REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                return ""
            return response.read(2_000_000).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def extract_text_from_html(raw_html: str, fallback: str = "") -> str:
    """Extract article body text from raw HTML using trafilatura when available."""
    if not raw_html:
        return fallback

    if _HAS_TRAFILATURA:
        try:
            result = trafilatura.extract(
                raw_html,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
                favor_recall=True,
            )
            if result and len(result) > max(len(fallback), 80):
                return result
        except Exception:
            pass

    text = _extract_with_fallback_parser(raw_html)
    return text if len(text) > len(fallback) else fallback


def fetch_readable_article_text(url: str, fallback: str = "") -> str:
    """
    Fetch a URL and return the clean article body text.
    Uses trafilatura when installed, falls back to a custom HTML parser.
    Returns `fallback` on any failure or if the extracted text is shorter.
    """
    if not url:
        return fallback
    raw = fetch_raw_html(url)
    if not raw:
        return fallback
    return extract_text_from_html(raw, fallback=fallback)
