import sys, time
sys.path.insert(0, ".")
from app.ingest.rss_ingest import _fetch_bing_news
import trafilatura

print("=== Bing News RSS test ===\n")
articles = _fetch_bing_news("pittsburgh steelers")
print(f"Got {len(articles)} articles\n")

for a in articles[:6]:
    print(f"  [{a.get('source_name')}] {a.get('title','')[:55]}")
    print(f"   url: {a.get('url','')[:80]}")
    print(f"   raw_text: {len(a.get('raw_text',''))} chars")
    print()

# Test trafilatura on the first 3 direct URLs
print("=== Enrichment test (trafilatura on Bing URLs) ===\n")
for a in articles[:3]:
    url = a.get("url", "")
    if not url or "news.google.com" in url:
        continue
    t0 = time.time()
    html = trafilatura.fetch_url(url)
    text = trafilatura.extract(html or "", favor_recall=True) if html else None
    elapsed = time.time() - t0
    src = a.get("source_name", "")
    title = a.get("title", "")[:50]
    print(f"  [{src}] {title}")
    if text:
        print(f"   -> {len(text):,} chars extracted in {elapsed:.1f}s")
        print(f"   -> {text[:120].replace(chr(10),' ')}")
    else:
        print(f"   -> FAILED ({elapsed:.1f}s)")
    print()
