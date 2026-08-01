#!/usr/bin/env python3
"""Remove leaked lightweight Markdown from already-published generated articles."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import close_pool, get_connection
from app.llm.article_generator import _plain_article_text


def main() -> int:
    changed = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, headline, dek, summary, body FROM generated_articles")
            for row in cur.fetchall():
                try:
                    body = json.loads(row["body"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    body = []
                clean_body = [_plain_article_text(item) for item in body] if isinstance(body, list) else body
                clean_headline = _plain_article_text(row["headline"])
                clean_dek = _plain_article_text(row["dek"])
                clean_summary = _plain_article_text(row["summary"])
                if (
                    clean_headline == row["headline"]
                    and clean_dek == row["dek"]
                    and clean_summary == row["summary"]
                    and clean_body == body
                ):
                    continue
                cur.execute(
                    """
                    UPDATE generated_articles
                    SET headline = %s, dek = %s, summary = %s, body = %s
                    WHERE id = %s
                    """,
                    (
                        clean_headline,
                        clean_dek,
                        clean_summary,
                        json.dumps(clean_body, ensure_ascii=False),
                        row["id"],
                    ),
                )
                changed += 1
    close_pool()
    print(f"Sanitized {changed} generated article(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
