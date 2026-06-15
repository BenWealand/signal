import sys; sys.path.insert(0, ".")
from app.ingest.guardian_ingest import fetch_guardian_articles

arts = fetch_guardian_articles("pittsburgh steelers", 3)
print(f"Guardian returned {len(arts)} articles")
for a in arts:
    title = a.get("title", "")[:60]
    src = a.get("source_name", "")
    rlen = len(a.get("raw_text", ""))
    preview = a.get("raw_text", "")[50:200].replace("\n", " ")
    print(f"  [{src}] {title}")
    print(f"   raw_text: {rlen:,} chars | {preview}")
    print()

# Also test a news topic
print("--- news topic: supply chain hack")
arts2 = fetch_guardian_articles("supply chain hack", 2)
print(f"Guardian returned {len(arts2)} articles")
for a in arts2:
    print(f"  {a.get('title','')[:70]} ({len(a.get('raw_text',''))} chars)")
