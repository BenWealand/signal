import sys, json, urllib.request, urllib.parse
sys.path.insert(0, ".")

query = "supply chain"
encoded = urllib.parse.quote_plus(query)
url = (
    f"https://content.guardianapis.com/search"
    f"?q={encoded}&api-key=test&show-fields=bodyText,trailText,headline"
    f"&order-by=relevance&page-size=3"
)
print("URL:", url)
try:
    req = urllib.request.Request(url, headers={"User-Agent": "SignalNewsBot/1.0"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read().decode()
    data = json.loads(raw)
    status = data.get("response", {}).get("status")
    total = data.get("response", {}).get("total", 0)
    results = data.get("response", {}).get("results", [])
    print(f"Status: {status}, total: {total}, results: {len(results)}")
    for r in results:
        fields = r.get("fields", {})
        body = fields.get("bodyText", "")
        print(f"  title: {r.get('webTitle','')[:60]}")
        print(f"  body len: {len(body)} chars")
        if body:
            print(f"  preview: {body[:100]}")
        print()
except Exception as e:
    print(f"ERROR: {e}")
