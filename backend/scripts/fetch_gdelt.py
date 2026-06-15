from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.db.connection import create_tables
from app.db.queries import insert_article
from app.ingest.gdelt_ingest import fetch_gdelt_articles


def configured_queries() -> list[str]:
    return [query.strip() for query in settings.gdelt_queries.split(",") if query.strip()]


if __name__ == "__main__":
    create_tables()
    inserted = 0
    for query in configured_queries():
        for article in fetch_gdelt_articles(query, limit=25):
            insert_article(article)
            inserted += 1
    print(f"Fetched {inserted} GDELT article candidates.")

