"""
Migration: add rss_url column to articles table if missing,
and purge non-Latin-script articles ingested before the language filter.
Run once from the backend directory: py scripts/migrate_add_rss_url.py
"""
from __future__ import annotations
import sys
sys.path.insert(0, ".")
from app.db.connection import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:
        # Add rss_url column if it doesn't exist
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='articles' AND column_name='rss_url'"
        )
        if not cur.fetchone():
            cur.execute("ALTER TABLE articles ADD COLUMN rss_url TEXT DEFAULT ''")
            print("Added rss_url column.")
        else:
            print("rss_url column already exists.")

        # Purge articles whose title is predominantly non-Latin script
        # (Chinese, Arabic, Hindi, etc. that snuck in before the language filter)
        cur.execute("SELECT id, title, source_name FROM articles")
        rows = cur.fetchall()
        to_delete = []
        for row in rows:
            title = str(row["title"] or "")
            letters = [c for c in title if c.isalpha()]
            if letters:
                latin = sum(1 for c in letters if ord(c) < 128)
                ratio = latin / len(letters)
                if ratio < 0.70:
                    to_delete.append(int(row["id"]))

        if to_delete:
            # Clean up dependent rows first
            cur.execute("DELETE FROM entities WHERE article_id = ANY(%s)", (to_delete,))
            cur.execute("DELETE FROM claims WHERE article_id = ANY(%s)", (to_delete,))
            cur.execute(
                "DELETE FROM story_cluster_articles WHERE article_id = ANY(%s)",
                (to_delete,)
            )
            cur.execute("DELETE FROM articles WHERE id = ANY(%s)", (to_delete,))
            print(f"Purged {len(to_delete)} non-Latin-script articles.")
        else:
            print("No non-Latin articles found to purge.")

    conn.commit()
    print("Migration complete.")
