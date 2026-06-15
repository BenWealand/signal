from __future__ import annotations

from urllib.parse import urlparse


DEFAULT_SOURCES = [
    {"source_name": "Reuters", "domain": "reuters.com", "country": "Global", "source_type": "wire", "reliability_tier": "high"},
    {"source_name": "Associated Press", "domain": "apnews.com", "country": "US", "source_type": "wire", "reliability_tier": "high"},
    {"source_name": "BBC", "domain": "bbc.com", "country": "UK", "source_type": "public", "reliability_tier": "high"},
    {"source_name": "PBS", "domain": "pbs.org", "country": "US", "source_type": "public", "reliability_tier": "high"},
    {"source_name": "NPR", "domain": "npr.org", "country": "US", "source_type": "public", "reliability_tier": "high", "political_lean_optional": "center-left"},
    {"source_name": "DW", "domain": "dw.com", "country": "DE", "source_type": "international", "reliability_tier": "standard"},
    {"source_name": "France 24", "domain": "france24.com", "country": "FR", "source_type": "international", "reliability_tier": "standard"},
    {"source_name": "Al Jazeera", "domain": "aljazeera.com", "country": "QA", "source_type": "international", "reliability_tier": "standard"},
    {"source_name": "The Guardian", "domain": "theguardian.com", "country": "UK", "source_type": "newspaper", "reliability_tier": "standard", "political_lean_optional": "left"},
    {"source_name": "CBC", "domain": "cbc.ca", "country": "CA", "source_type": "public", "reliability_tier": "standard"},
    {"source_name": "CNN", "domain": "cnn.com", "country": "US", "source_type": "cable", "reliability_tier": "standard", "political_lean_optional": "left"},
    {"source_name": "Fox News", "domain": "foxnews.com", "country": "US", "source_type": "cable", "reliability_tier": "standard", "political_lean_optional": "right"},
    {"source_name": "MSNBC", "domain": "msnbc.com", "country": "US", "source_type": "cable", "reliability_tier": "standard", "political_lean_optional": "left"},
    {"source_name": "National Review", "domain": "nationalreview.com", "country": "US", "source_type": "magazine", "reliability_tier": "opinion-heavy", "political_lean_optional": "right"},
    {"source_name": "The Atlantic", "domain": "theatlantic.com", "country": "US", "source_type": "magazine", "reliability_tier": "standard", "political_lean_optional": "left"},
    {"source_name": "Washington Examiner", "domain": "washingtonexaminer.com", "country": "US", "source_type": "newspaper", "reliability_tier": "standard", "political_lean_optional": "right"},
]


# Domains that should never be used as article sources — social media,
# link aggregators, and image hosts produce no scrapable article content.
BLOCKED_DOMAINS: frozenset[str] = frozenset({
    "facebook.com", "fb.com", "m.facebook.com",
    "twitter.com", "x.com", "t.co",
    "instagram.com",
    "tiktok.com",
    "reddit.com", "redd.it",
    "youtube.com", "youtu.be",
    "linkedin.com",
    "pinterest.com",
    "snapchat.com",
    "threads.net",
    "tumblr.com",
    "imgur.com",
    "flickr.com",
})


def is_blocked_domain(url: str) -> bool:
    """Return True if the URL's domain is on the social-media / non-article blocklist."""
    d = domain_from_url(url)
    return any(d == blocked or d.endswith("." + blocked) for blocked in BLOCKED_DOMAINS)


def domain_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.removeprefix("www.")


def guess_source_from_url(url: str) -> str:
    domain = domain_from_url(url)
    for source in DEFAULT_SOURCES:
        if source["domain"] and source["domain"] in domain:
            return source["source_name"]
    return domain or "Unknown source"

