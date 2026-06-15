from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db.connection import create_tables
from app.db.queries import insert_article
from app.ingest.rss_ingest import fetch_rss_articles


def configured_feeds() -> list[tuple[str, str]]:
    feeds = []
    for entry in settings.rss_feeds.split(","):
        if not entry.strip():
            continue
        if "|" in entry:
            name, url = entry.split("|", 1)
        else:
            name, url = "RSS", entry
        feeds.append((name.strip(), url.strip()))
    return feeds


if __name__ == "__main__":
    create_tables()
    inserted = 0
    for source_name, feed_url in configured_feeds():
        for article in fetch_rss_articles(feed_url, source_name):
            insert_article(article)
            inserted += 1
    print(f"Fetched {inserted} RSS articles.")

