#!/usr/bin/env python3
"""Print current and recent durable article-generation jobs."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import close_pool, get_connection


def main() -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, COUNT(*) AS count,
                       ROUND(EXTRACT(EPOCH FROM (NOW() - MIN(created_at))) / 60, 1) AS oldest_minutes
                FROM article_generation_jobs
                WHERE status IN ('queued', 'sourcing', 'ready_for_generation', 'generating')
                GROUP BY status
                ORDER BY status
                """
            )
            counts = list(cur.fetchall())
            cur.execute(
                """
                SELECT id, status, priority, LEFT(prompt, 90) AS prompt,
                       created_at, started_at, finished_at,
                       ROUND(EXTRACT(EPOCH FROM (NOW() - created_at)) / 60, 1) AS age_minutes,
                       LEFT(COALESCE(error, ''), 180) AS error
                FROM article_generation_jobs
                ORDER BY created_at DESC
                LIMIT 30
                """
            )
            recent = list(cur.fetchall())
    close_pool()
    print("ACTIVE COUNTS")
    for row in counts:
        print(dict(row))
    print("RECENT JOBS")
    for row in recent:
        print(dict(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
