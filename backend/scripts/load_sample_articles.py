from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.connection import create_tables
from app.db.queries import insert_article
from app.ingest.source_registry import DEFAULT_SOURCES
from app.db.queries import replace_sources


SAMPLE_ARTICLES = [
    {
        "source_name": "Reuters",
        "title": "Senate passes climate bill in close Thursday vote",
        "url": "https://example.com/reuters/senate-climate-bill",
        "published_at": "2026-05-07T09:10:00Z",
        "raw_text": "The Senate passed the climate bill on Thursday by a vote of 54-46. The bill includes funding for coastal flood mitigation and grid resilience. The White House said the measure would be reviewed before final signing.",
    },
    {
        "source_name": "Associated Press",
        "title": "Climate legislation clears Senate after 54-46 vote",
        "url": "https://example.com/ap/climate-legislation-senate",
        "published_at": "2026-05-07T09:18:00Z",
        "raw_text": "The Senate approved the climate legislation Thursday in a 54-46 vote. The proposal directs money toward coastal flood protection and electrical grid upgrades. House leaders said a final procedural review is still expected.",
    },
    {
        "source_name": "BBC",
        "title": "US Senate approves climate bill with flood funding",
        "url": "https://example.com/bbc/us-senate-climate-bill",
        "published_at": "2026-05-07T09:25:00Z",
        "raw_text": "The United States Senate passed a climate bill by 54 to 46 on Thursday. The bill contains money for flood prevention in coastal areas. Some economic impact claims remain uncertain because agencies have not published final estimates.",
    },
]


if __name__ == "__main__":
    create_tables()
    replace_sources(DEFAULT_SOURCES)
    ids = [insert_article(article) for article in SAMPLE_ARTICLES]
    print(f"Loaded {len(ids)} sample articles: {ids}")
