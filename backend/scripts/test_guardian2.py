import sys, traceback
sys.path.insert(0, ".")

import json, urllib.parse, urllib.request

_API_BASE = "https://content.guardianapis.com/search"
_API_KEY = "test"

def fetch_guardian_articles_debug(query, max_articles=5):
    encoded = urllib.parse.quote_plus(query)
    url = (
        f"{_API_BASE}"
        f"?q={encoded}"
        f"&api-key={_API_KEY}"
        f"&show-fields=bodyText,trailText,headline,byline"
        f"&order-by=relevance"
        f"&page-size={min(max_articles, 10)}"
    )
    print("Fetching:", url[:100])
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "SignalNewsBot/1.0 (news transparency research)"},
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))

        results = data.get("response", {}).get("results", [])
        print(f"Raw results count: {len(results)}")
        articles = []
        for item in results:
            fields = item.get("fields", {})
            body  = (fields.get("bodyText")  or "").strip()
            trail = (fields.get("trailText") or "").strip()
            headline = (fields.get("headline") or item.get("webTitle") or "").strip()
            article_url  = item.get("webUrl", "")
            pub_date     = item.get("webPublicationDate", "")
            section      = item.get("sectionName", "")
            print(f"  item: headline={headline[:40]} body={len(body)} trail={len(trail)}")
            content = body if len(body) > len(trail) else trail
            if not content:
                print("    -> SKIPPED (no content)")
                continue
            articles.append({
                "source_name": "The Guardian",
                "domain": "theguardian.com",
                "title": headline,
                "url": article_url,
                "raw_text": f"{headline}. {content}",
            })
        return articles
    except Exception as e:
        traceback.print_exc()
        return []

arts = fetch_guardian_articles_debug("supply chain hack")
print(f"\nFinal: {len(arts)} articles")
