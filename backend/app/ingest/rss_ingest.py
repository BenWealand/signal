from __future__ import annotations

import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed

from app.ingest.article_reader import (
    fetch_readable_article_text, extract_text_from_html,
    fetch_raw_html, _unwrap_google_news_url, unwrap_bing_news_url,
)
from app.ingest.source_registry import domain_from_url, is_blocked_domain


# ── Feed registry ─────────────────────────────────────────────────────────────
# Each entry: (feed_url, source_name)
# Organised by section so callers can ask for a specific topic.

SECTION_FEEDS: dict[str, list[tuple[str, str]]] = {
    "world": [
        ("https://feeds.apnews.com/rss/apf-topnews",        "AP News"),
        ("https://feeds.apnews.com/rss/apf-intlnews",       "AP News"),
        ("http://feeds.bbci.co.uk/news/world/rss.xml",      "BBC"),
        ("http://feeds.bbci.co.uk/news/rss.xml",            "BBC"),
        ("https://www.aljazeera.com/xml/rss/all.xml",       "Al Jazeera"),
        ("https://feeds.npr.org/1001/rss.xml",              "NPR"),
        ("https://www.theguardian.com/world/rss",           "The Guardian"),
        ("https://www.pbs.org/newshour/feeds/rss/headlines","PBS NewsHour"),
        ("https://rss.dw.com/rdf/rss-en-all",               "Deutsche Welle"),
    ],
    "politics": [
        ("https://feeds.apnews.com/rss/apf-politics",                  "AP News"),
        ("https://feeds.npr.org/1014/rss.xml",                         "NPR"),
        ("https://www.theguardian.com/us-news/rss",                    "The Guardian"),
        ("https://rss.politico.com/politics-news.xml",                 "Politico"),
        ("http://feeds.bbci.co.uk/news/politics/rss.xml",              "BBC"),
        ("https://thehill.com/feed/",                                  "The Hill"),
    ],
    "sports": [
        ("https://feeds.bbci.co.uk/sport/rss.xml",                     "BBC Sport"),
        ("https://www.theguardian.com/sport/rss",                      "The Guardian"),
        ("https://feeds.npr.org/1055/rss.xml",                         "NPR"),
        ("https://www.espn.com/espn/rss/news",                         "ESPN"),
        ("https://feeds.bbci.co.uk/sport/football/rss.xml",            "BBC Football"),
    ],
    "markets": [
        ("https://feeds.apnews.com/rss/apf-business",                  "AP News"),
        ("https://www.theguardian.com/business/rss",                   "The Guardian"),
        ("http://feeds.bbci.co.uk/news/business/rss.xml",              "BBC"),
        ("https://www.cnbc.com/id/100003114/device/rss/rss.html",      "CNBC"),
        ("https://feeds.marketwatch.com/marketwatch/topstories/",      "MarketWatch"),
        ("https://feeds.reuters.com/reuters/businessNews",             "Reuters"),
    ],
    "technology": [
        ("https://feeds.apnews.com/rss/apf-technology",                "AP News"),
        ("https://www.theguardian.com/technology/rss",                 "The Guardian"),
        ("http://feeds.bbci.co.uk/news/technology/rss.xml",            "BBC"),
        ("http://feeds.arstechnica.com/arstechnica/index/",            "Ars Technica"),
        ("https://feeds.wired.com/wired/index",                        "Wired"),
        ("https://www.technologyreview.com/feed/",                     "MIT Tech Review"),
        ("https://feeds.feedburner.com/TechCrunch",                    "TechCrunch"),
        ("https://www.theverge.com/rss/index.xml",                     "The Verge"),
    ],
    "climate": [
        ("https://www.theguardian.com/environment/rss",                "The Guardian"),
        ("https://feeds.apnews.com/rss/apf-science",                   "AP News"),
        ("http://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "BBC"),
        ("https://insideclimatenews.org/feed/",                        "Inside Climate News"),
        ("https://grist.org/feed/",                                    "Grist"),
        ("https://feeds.reuters.com/reuters/environment",              "Reuters"),
    ],
    "source-wire": [
        ("https://feeds.apnews.com/rss/apf-topnews",                   "AP News"),
        ("http://feeds.bbci.co.uk/news/rss.xml",                       "BBC"),
        ("https://feeds.npr.org/1001/rss.xml",                         "NPR"),
        ("https://www.aljazeera.com/xml/rss/all.xml",                  "Al Jazeera"),
        ("https://feeds.reuters.com/reuters/topNews",                  "Reuters"),
        ("https://www.pbs.org/newshour/feeds/rss/headlines",           "PBS NewsHour"),
    ],
}

# Flat list: (section, feed_url, source_name) — every unique feed once
_seen_urls: set[str] = set()
ALL_FEEDS: list[tuple[str, str, str]] = []
for _section, _feeds in SECTION_FEEDS.items():
    for _url, _name in _feeds:
        if _url not in _seen_urls:
            _seen_urls.add(_url)
            ALL_FEEDS.append((_section, _url, _name))


# ── Parsing helpers ────────────────────────────────────────────────────────────

import html as _html_module

_GN_TITLE_SEP = re.compile(r"\s*[-–—]?\s*&nbsp;.*$|\s+[-–—]\s+[A-Z][^-]{2,40}$")
# Matches the Facebook/social sharing suffix: "| See link below ⬇️ 📸 ..."
_SOCIAL_SUFFIX = re.compile(r"\s*[|｜]\s*see link.*$", re.IGNORECASE)
# Strip emoji characters
_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FFFF"   # misc symbols, pictographs, transport, etc.
    "\U00002600-\U000027BF"   # misc symbols
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U00002000-\U0000206F"   # general punctuation
    "]+",
    flags=re.UNICODE,
)
# Photo credit patterns: "📸 Author, Outlet" or "Photo: Author"
_PHOTO_CREDIT = re.compile(
    r"(📸|photo\s*[:/])\s*.{0,80}?(imagn images?|getty images?|usa today|ap photo|reuters|afp)[^.]*",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = _html_module.unescape(text)          # &nbsp; → space, &amp; → &, etc.
    return re.sub(r"\s+", " ", text).strip()


def _clean_title(title: str, is_google: bool = False) -> str:
    """
    Clean RSS titles:
    - Decode HTML entities
    - Remove &nbsp; / zero-width chars
    - Strip social-media "| See link below ⬇️" suffixes
    - Strip photo-credit annotations (📸 Author / Getty Images)
    - Strip emoji
    - For Google News, also strip the " - Publisher Name" suffix
    """
    title = _html_module.unescape(title)
    title = re.sub(r"[\xa0\u200b]+.*$", "", title)      # non-breaking space → truncate
    title = _SOCIAL_SUFFIX.sub("", title)                # | See link below ...
    title = _PHOTO_CREDIT.sub("", title)                 # photo credits
    title = _EMOJI.sub("", title)                        # emoji
    if is_google:
        title = _GN_TITLE_SEP.sub("", title)             # " - Publisher Name"
    return title.strip().strip("-–—|").strip()


def _parse_rss_xml(xml_text: str, source_name: str, section: str, feed_url: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    is_google = "news.google.com" in feed_url

    items: list[dict] = []
    for item in root.findall(".//item"):
        raw_title = (item.findtext("title") or "Untitled").strip()
        link = (item.findtext("link") or "").strip()
        description = _strip_html(item.findtext("description") or "")
        pub_date = (item.findtext("pubDate") or "").strip()

        # For Google News items, the <source> child element carries the real
        # publisher name and domain, e.g.:
        #   <source url="https://thehackernews.com">The Hacker News</source>
        publisher_name = source_name
        publisher_url = ""
        source_el = item.find("source")
        if source_el is not None:
            if source_el.text and source_el.text.strip():
                publisher_name = source_el.text.strip()
            publisher_url = source_el.get("url", "")

        title = _clean_title(raw_title, is_google=is_google)

        # Some feeds embed full content in <content:encoded>
        content_el = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
        content_text = _strip_html(content_el.text if content_el is not None else "")

        raw_text = content_text if len(content_text) > len(description) else description
        raw_text = f"{title}. {raw_text}".strip()

        if not link or not title or title == "Untitled":
            continue

        # Unwrap aggregator redirect URLs to get the real publisher article URL
        if "news.google.com" in link:
            real_link = _unwrap_google_news_url(link)
        elif "bing.com/news/apiclick" in link:
            real_link = unwrap_bing_news_url(link)
        else:
            real_link = link

        # Skip social media and other non-article domains entirely
        if is_blocked_domain(real_link):
            continue

        # If we successfully decoded a Bing/Google redirect, use the real domain
        # to set a better source_name when the RSS didn't provide one
        if real_link != link and publisher_name in ("Bing News", "Google News"):
            from app.ingest.source_registry import domain_from_url as _dfurl
            publisher_name = _dfurl(real_link).replace("www.", "").split(".")[0].title() or publisher_name

        items.append({
            "source_name": publisher_name,
            "domain": domain_from_url(publisher_url or real_link),
            "title": title,
            "url": real_link,
            "published_at": pub_date,
            "description": description[:500],
            "raw_text": raw_text,
            "topic": section,
            "rss_url": feed_url,
            "language": "en",
            "status": "new",
        })
    return items


# ── Network helpers ────────────────────────────────────────────────────────────

def _fetch_one_feed(feed_url: str, source_name: str, section: str) -> list[dict]:
    try:
        req = urllib.request.Request(
            feed_url,
            headers={"User-Agent": "SignalNewsBot/1.0 (RSS reader; news transparency research)"},
        )
        with urllib.request.urlopen(req, timeout=14) as resp:
            xml_text = resp.read(3_000_000).decode("utf-8", errors="ignore")
        return _parse_rss_xml(xml_text, source_name, section, feed_url)
    except Exception:
        return []


def _enrich_article(article: dict, timeout: int = 14) -> dict:
    """Replace title+description snippet with full article text via trafilatura."""
    url = article.get("url", "")
    if not url:
        return article
    raw_html = fetch_raw_html(url, timeout=timeout)
    if not raw_html:
        return article
    full_text = extract_text_from_html(raw_html, fallback=article.get("raw_text", ""))
    return {**article, "raw_text": full_text}


# ── Public API ─────────────────────────────────────────────────────────────────

def fetch_section_rss(
    section: str,
    enrich: bool = True,
    max_articles: int = 40,
    enrich_workers: int = 10,
) -> list[dict]:
    """
    Fetch all RSS articles for one section.
    enrich=True: follow each URL with trafilatura to get full article text.
    enrich=False: return title + RSS description only (fast, ~2-4 seconds).
    """
    feeds = SECTION_FEEDS.get(section.lower().replace(" ", "-"), [])
    if not feeds:
        return []

    raw_articles: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        futures = [pool.submit(_fetch_one_feed, url, name, section) for url, name in feeds]
        for future in as_completed(futures):
            raw_articles.extend(future.result())

    # Deduplicate by URL
    seen: set[str] = set()
    unique: list[dict] = []
    for a in raw_articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)

    articles = unique[:max_articles]

    if not enrich:
        return articles

    enriched: list[dict] = []
    with ThreadPoolExecutor(max_workers=enrich_workers) as pool:
        futures_map = {pool.submit(_enrich_article, a): a for a in articles}
        for future in as_completed(futures_map):
            try:
                enriched.append(future.result())
            except Exception:
                enriched.append(futures_map[future])

    return enriched


def fetch_all_rss_fast(max_per_section: int = 8) -> list[dict]:
    """
    Quick startup fetch: all sections, NO full-text enrichment.
    Typically finishes in 5-10 seconds with 20+ feeds running in parallel.
    """
    all_articles: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(ALL_FEEDS)) as pool:
        futures = [
            pool.submit(_fetch_one_feed, url, name, section)
            for section, url, name in ALL_FEEDS
        ]
        section_counts: dict[str, int] = {}
        for future in as_completed(futures):
            for article in future.result():
                section = article.get("topic", "world")
                section_counts[section] = section_counts.get(section, 0)
                if section_counts[section] < max_per_section:
                    all_articles.append(article)
                    section_counts[section] += 1

    seen: set[str] = set()
    unique: list[dict] = []
    for a in all_articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    return unique


def enrich_articles_in_background(articles: list[dict], workers: int = 8) -> list[dict]:
    """
    Given a list of articles (already in DB with snippet text), fetch full text
    for each. Returns the enriched list. Intended to be called from a daemon thread.
    """
    enriched: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures_map = {pool.submit(_enrich_article, a): a for a in articles}
        for future in as_completed(futures_map):
            try:
                enriched.append(future.result())
            except Exception:
                enriched.append(futures_map[future])
    return enriched


# ── Query-time search (called per user prompt, not on a schedule) ─────────────

def fetch_articles_for_query_fast(
    query: str,
    max_articles: int = 8,
    min_candidates: int = 4,
    timeout_s: float = 5.0,
) -> list[dict]:
    """
    Fast-mode live discovery: race Bing News + Guardian only, stop early when
    enough usable candidates exist. No full-page enrichment.
    """
    from app.ingest.guardian_ingest import fetch_guardian_articles

    raw_articles: list[dict] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            pool.submit(_fetch_bing_news, query): "bing",
            pool.submit(fetch_guardian_articles, query, min(5, max_articles)): "guardian",
        }
        try:
            for future in as_completed(futures, timeout=timeout_s):
                try:
                    raw_articles.extend(future.result() or [])
                except Exception:
                    continue
                usable = [
                    a for a in raw_articles
                    if a.get("url") and not is_blocked_domain(a.get("url", ""))
                    and (
                        len(a.get("raw_text", "") or "") > 80
                        or len(a.get("description", "") or "") > 40
                        or len(a.get("title", "") or "") > 20
                    )
                ]
                if len({a.get("url") for a in usable}) >= min_candidates:
                    break
        except TimeoutError:
            pass
        finally:
            for future in futures:
                future.cancel()

    seen: set[str] = set()
    unique: list[dict] = []
    for article in raw_articles:
        url = article.get("url", "")
        if not url or url in seen or is_blocked_domain(url):
            continue
        seen.add(url)
        if not article.get("raw_text") and article.get("description"):
            article = {**article, "raw_text": article["description"]}
        unique.append(article)
        if len(unique) >= max_articles:
            break
    return unique


# Topic-aware supplemental feeds: keyed by keyword → list of (url, source_name)
# Added alongside the Google News query feed for richer, scrapable content.
_TOPIC_FEEDS: dict[str, list[tuple[str, str]]] = {
    "sports": [
        ("https://www.espn.com/espn/rss/news", "ESPN"),
        ("https://www.cbssports.com/rss/headlines/", "CBS Sports"),
    ],
    "nfl": [
        ("https://www.espn.com/espn/rss/nfl/news", "ESPN NFL"),
        ("https://www.cbssports.com/rss/headlines/nfl/", "CBS Sports NFL"),
        ("https://feeds.apnews.com/rss/apf-sports", "AP Sports"),
    ],
    "nba": [
        ("https://www.espn.com/espn/rss/nba/news", "ESPN NBA"),
        ("https://www.cbssports.com/rss/headlines/nba/", "CBS Sports NBA"),
    ],
    "mlb": [
        ("https://www.espn.com/espn/rss/mlb/news", "ESPN MLB"),
        ("https://www.cbssports.com/rss/headlines/mlb/", "CBS Sports MLB"),
    ],
    "nhl": [
        ("https://www.espn.com/espn/rss/nhl/news", "ESPN NHL"),
    ],
    "soccer": [
        ("https://www.espn.com/espn/rss/soccer/news", "ESPN Soccer"),
        ("https://www.theguardian.com/football/rss", "The Guardian Football"),
    ],
    "tech": [
        ("http://feeds.arstechnica.com/arstechnica/index/", "Ars Technica"),
        ("https://www.theverge.com/rss/index.xml", "The Verge"),
        ("https://feeds.wired.com/wired/index", "Wired"),
    ],
    "crypto": [
        ("https://feeds.feedburner.com/CoinDesk", "CoinDesk"),
    ],
    "science": [
        ("https://feeds.apnews.com/rss/apf-science", "AP Science"),
        ("https://www.newscientist.com/feed/home/", "New Scientist"),
    ],
}

# NFL teams — maps keyword to "nfl" topic bucket
_NFL_TEAMS = frozenset({
    "steelers","patriots","cowboys","eagles","packers","bears","vikings","lions",
    "ravens","browns","bengals","texans","colts","jaguars","titans","chiefs",
    "raiders","chargers","broncos","seahawks","rams","niners","cardinals","falcons",
    "saints","panthers","buccaneers","giants","jets","commanders","bills","dolphins",
})
_NBA_TEAMS = frozenset({
    "lakers","celtics","warriors","bulls","heat","knicks","nets","sixers",
    "bucks","nuggets","suns","clippers","mavs","mavericks","rockets","spurs",
    "jazz","grizzlies","pelicans","thunder","blazers","cavaliers","pistons",
    "pacers","hawks","hornets","wizards","magic","raptors","timberwolves","kings",
})

_STOPWORDS_QUERY = frozenset({
    "the","a","an","and","or","of","in","on","for","is","was","at","to",
    "from","with","by","that","this","it","be","are","were","has","have",
})


def _topic_feeds_for_query(query: str) -> list[tuple[str, str]]:
    """Return extra RSS feeds that match the query topic."""
    q = query.lower()
    words = frozenset(re.findall(r"[a-z]{3,}", q))
    feeds: list[tuple[str, str]] = []
    seen: set[str] = set()

    def _add(key: str) -> None:
        for item in _TOPIC_FEEDS.get(key, []):
            if item[0] not in seen:
                seen.add(item[0])
                feeds.append(item)

    # Sports team detection
    if words & _NFL_TEAMS or "nfl" in words or "football" in words:
        _add("nfl")
    if words & _NBA_TEAMS or "nba" in words or "basketball" in words:
        _add("nba")
    if "mlb" in words or "baseball" in words:
        _add("mlb")
    if "nhl" in words or "hockey" in words:
        _add("nhl")
    if "soccer" in words or "football" in words or "premier" in words or "fifa" in words:
        _add("soccer")

    # Tech topics
    if words & {"tech","technology","software","hardware","ai","startup","cyber","hack","crypto","blockchain"}:
        _add("tech")
    if words & {"bitcoin","ethereum","crypto","blockchain","defi","nft"}:
        _add("crypto")
    if words & {"science","research","study","discovery","nasa","space","biology","climate"}:
        _add("science")

    # Always add sports fallback if any team/sport is detected
    if feeds:
        _add("sports")

    return feeds


def _fetch_bing_news(query: str, section: str = "") -> list[dict]:
    """
    Fetch news articles from Bing News RSS.
    Bing returns DIRECT publisher URLs (Reuters, AP, Bloomberg, CNN, etc.)
    so trafilatura can scrape the actual articles — unlike Google News which
    wraps all URLs in a JavaScript shell.
    """
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.bing.com/news/search?q={encoded}&format=RSS&mkt=en-US"
    items = _fetch_one_feed(url, "Bing News", section or query)
    # Bing RSS items use <source> for the actual publisher — already parsed by
    # _parse_rss_xml. Mark them so enrichment knows to scrape them.
    return items


# Always-on multi-outlet supplements for every query
_BASE_QUERY_FEEDS: list[tuple[str, str]] = [
    ("https://feeds.apnews.com/rss/apf-topnews",           "AP News"),
    ("http://feeds.bbci.co.uk/news/rss.xml",               "BBC"),
    ("https://feeds.reuters.com/reuters/topNews",          "Reuters"),
    ("https://feeds.npr.org/1001/rss.xml",                 "NPR"),
    ("https://www.theguardian.com/world/rss",              "The Guardian"),
    ("https://rss.dw.com/rdf/rss-en-all",                  "Deutsche Welle"),
    ("https://www.aljazeera.com/xml/rss/all.xml",          "Al Jazeera"),
]


def fetch_articles_for_query(
    query: str,
    enrich: bool = True,
    max_articles: int = 50,
    enrich_workers: int = 20,
) -> list[dict]:
    """
    Dynamically fetch articles for an arbitrary user search query from
    multiple independent outlets so claim-consensus detection is meaningful.

    Sources (run in parallel):
    1. Bing News RSS   — direct publisher URLs from Reuters, AP, Bloomberg, CNN,
                         Politico, etc.  trafilatura can scrape these fully.
    2. The Guardian API — full article body text, covers all topics.
    3. Topic RSS feeds  — ESPN/CBS for sports; Ars Technica/Wired for tech; etc.
    4. Core wire feeds  — AP, BBC, Reuters, NPR, Al Jazeera (always fresh).

    Google News is intentionally excluded — its URLs resolve to a JS app
    shell that returns zero extractable text.

    All non-Guardian articles are enriched in parallel with trafilatura to
    replace RSS snippets with full article body text from the publisher.
    """
    from app.ingest.guardian_ingest import fetch_guardian_articles
    from app.ingest.newsapi_ingest import fetch_newsapi_articles
    from app.ingest.currents_ingest import fetch_currents_articles
    from app.ingest.gnews_ingest import fetch_gnews_articles

    query_words = frozenset(
        w for w in re.findall(r"[a-z]{3,}", query.lower()) if w not in _STOPWORDS_QUERY
    )

    extra_feeds = _topic_feeds_for_query(query)
    all_feed_jobs = extra_feeds + _BASE_QUERY_FEEDS

    raw_articles: list[dict] = []

    with ThreadPoolExecutor(max_workers=max(8, len(all_feed_jobs) + 5)) as pool:
        futures = [
            pool.submit(_fetch_bing_news, query),
            pool.submit(fetch_guardian_articles, query, 5),   # 5 of 500/day
            pool.submit(fetch_newsapi_articles, query, 8),    # 8 of 100/day
            pool.submit(fetch_currents_articles, query, 8),   # 8 of 600/day
            pool.submit(fetch_gnews_articles, query, 8),      # 8 of 100/day
        ]
        for feed_url, source_name in all_feed_jobs:
            futures.append(pool.submit(_fetch_one_feed, feed_url, source_name, query))
        for future in as_completed(futures):
            raw_articles.extend(future.result())

    # URL patterns to always skip (live blogs, tag pages, etc.)
    _SKIP_URL_PATTERNS = (
        "/as-it-happened", "/live/", "/live-blog", "/liveblog",
        "/tag/", "/topics/", "/author/", "/search?",
    )

    # De-duplicate by URL, block social media and low-quality URL patterns
    seen: set[str] = set()
    unique: list[dict] = []
    for a in raw_articles:
        url = a.get("url", "")
        if not url or url in seen or is_blocked_domain(url):
            continue
        url_lower = url.lower()
        if any(pat in url_lower for pat in _SKIP_URL_PATTERNS):
            continue
        seen.add(url)
        unique.append(a)

    # Relevance filter:
    # - Build a normalised query phrase (e.g. "formula one") and require it
    #   to appear as a substring in the article title or description.
    # - For single-keyword queries fall back to word-set intersection.
    query_lower  = query.lower().strip()
    query_phrase = re.sub(r"\s+", " ", query_lower)   # normalise whitespace

    if query_words:
        def _is_relevant_article(a: dict) -> bool:
            title = a.get("title", "").lower()
            desc  = (a.get("description") or a.get("raw_text", "")).lower()
            combined_text = f"{title} {desc}"

            # Phrase match: if the whole query (or 2+ consecutive words) appears
            if query_phrase in combined_text:
                return True

            # Adjacent bigram match for 2+ word queries
            words_list = [w for w in re.findall(r"[a-z]{3,}", query_lower)
                          if w not in _STOPWORDS_QUERY]
            if len(words_list) >= 2:
                bigrams = [f"{words_list[i]} {words_list[i+1]}"
                           for i in range(len(words_list) - 1)]
                if any(bg in combined_text for bg in bigrams):
                    return True
                # Require at least 2 keywords to match for multi-word queries
                kw_matches = sum(1 for w in words_list if w in combined_text)
                return kw_matches >= 2

            # Single keyword: must appear in title (not just body text)
            return bool(query_words & (frozenset(re.findall(r"[a-z]{3,}", title)) - _STOPWORDS_QUERY))

        relevant = [a for a in unique if _is_relevant_article(a)]
        articles = relevant if relevant else unique
    else:
        articles = unique

    articles = articles[:max_articles]

    if not enrich or not articles:
        return articles

    # These sources already provide full/partial text via their APIs — no scraping needed.
    _NO_ENRICH = frozenset({"The Guardian", "NewsAPI", "Currents", "GNews"})

    from app.config import settings
    enrich_cap = max(4, int(settings.thorough_enrich_limit))
    enrich_timeout = max(4, int(settings.thorough_enrich_timeout_seconds))

    # Prefer already-rich text, then scrape only the top remaining candidates.
    articles.sort(key=lambda a: len(a.get("raw_text", "") or a.get("description", "")), reverse=True)
    to_enrich = [a for a in articles if a.get("source_name") not in _NO_ENRICH][:enrich_cap]
    enrich_ids = {id(a) for a in to_enrich}
    pre_enriched = [a for a in articles if id(a) not in enrich_ids]

    enriched: list[dict] = list(pre_enriched)
    if to_enrich:
        with ThreadPoolExecutor(max_workers=min(enrich_workers, len(to_enrich))) as pool:
            futures_map = {
                pool.submit(_enrich_article, a, enrich_timeout): a for a in to_enrich
            }
            for future in as_completed(futures_map):
                orig = futures_map[future]
                try:
                    result = future.result()
                    orig_len = len(orig.get("raw_text", ""))
                    new_len  = len(result.get("raw_text", ""))
                    # Accept enriched version if it added substantial text (150+ chars more)
                    enriched.append(result if new_len > orig_len + 150 else orig)
                except Exception:
                    enriched.append(orig)

    # Sort: richest text first — drives article body synthesis
    enriched.sort(key=lambda a: len(a.get("raw_text", "")), reverse=True)
    return enriched
