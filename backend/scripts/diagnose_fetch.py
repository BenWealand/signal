"""
Diagnose article fetching: tests trafilatura + Google News URL decoding
on a real set of URLs.
"""
import sys, time
sys.path.insert(0, ".")

import trafilatura
from app.ingest.article_reader import fetch_raw_html, _unwrap_google_news_url

TEST_URLS = [
    # A known good article URL (should work)
    "https://therecord.media/",
    "https://thehackernews.com/",
    "https://arstechnica.com/",
    # Google News RSS URL patterns (simulated, shows if decoder works)
    "https://news.google.com/rss/articles/CBMiXmh0dHBzOi8vd3d3LmJiYy5jb20vbmV3cy93b3JsZC11cy1jYW5hZGEtNjc4OTAxMjM",
]

print("=== trafilatura version:", trafilatura.__version__)
print()

for url in TEST_URLS:
    print(f"--- {url[:80]}")
    start = time.time()

    # Test URL unwrapping
    if "news.google.com" in url:
        unwrapped = _unwrap_google_news_url(url)
        print(f"  Unwrapped: {unwrapped[:80]}")
        url = unwrapped

    # Test trafilatura.fetch_url
    try:
        html = trafilatura.fetch_url(url)
        elapsed = time.time() - start
        if html:
            print(f"  fetch_url: OK ({len(html):,} bytes, {elapsed:.1f}s)")
            # Try to extract text
            text = trafilatura.extract(html, include_comments=False, favor_recall=True)
            if text:
                print(f"  extract:   OK ({len(text):,} chars)")
                print(f"  Preview:   {text[:150].replace(chr(10), ' ')}")
            else:
                print(f"  extract:   FAILED (no text extracted)")
        else:
            print(f"  fetch_url: FAILED (returned None, {elapsed:.1f}s)")
    except Exception as e:
        print(f"  fetch_url: ERROR - {e}")
    print()
