"""
Test the full article-fetch pipeline for a real query.
Shows: URLs fetched, whether they were decoded, and whether text was extracted.
"""
import sys, time
sys.path.insert(0, ".")

from app.ingest.rss_ingest import fetch_articles_for_query
from app.ingest.article_reader import fetch_raw_html, _unwrap_google_news_url
import trafilatura

QUERY = "pittsburgh steelers"

print(f"=== Testing query: '{QUERY}'")
print()

# Step 1: fetch RSS articles (no enrichment yet)
print("--- Step 1: fetching RSS candidates (enrich=False)...")
t0 = time.time()
articles = fetch_articles_for_query(QUERY, enrich=False, max_articles=10, enrich_workers=1)
print(f"  Got {len(articles)} articles in {time.time()-t0:.1f}s")
print()

for i, a in enumerate(articles[:8]):
    url = a.get("url", "")
    title = a.get("title", "")[:60]
    source = a.get("source_name", "")
    raw_len = len(a.get("raw_text", ""))
    print(f"  [{i+1}] {source}: {title}")
    print(f"       url={url[:80]}")
    print(f"       raw_text_len={raw_len} chars")

print()
print("--- Step 2: testing trafilatura enrichment on first 3 URLs...")
for a in articles[:3]:
    url = a.get("url", "")
    print(f"\n  Fetching: {url[:70]}")
    t0 = time.time()
    html = trafilatura.fetch_url(url) if url else None
    if html:
        text = trafilatura.extract(html, include_comments=False, favor_recall=True)
        elapsed = time.time() - t0
        print(f"  -> HTML {len(html):,} bytes, text {len(text or ''):,} chars ({elapsed:.1f}s)")
        if text:
            print(f"  -> Preview: {text[:120].replace(chr(10), ' ')}")
        else:
            print(f"  -> extract() returned None (homepage, paywall, or bot-blocked)")
    else:
        print(f"  -> fetch_url returned None (blocked/timeout)")
