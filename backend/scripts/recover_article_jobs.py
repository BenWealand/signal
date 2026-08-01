#!/usr/bin/env python3
"""Return interrupted jobs in one worker lane to a safe durable state."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import close_pool, get_connection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lane", choices=("all", "website", "x"), default="all")
    args = parser.parse_args()
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE article_generation_jobs
                SET status = CASE
                      WHEN status = 'generating' THEN 'ready_for_generation'
                      ELSE 'queued'
                    END,
                    error = ''
                WHERE status IN ('sourcing', 'generating')
                  AND (
                    %s = 'all'
                    OR CASE
                         WHEN payload->>'sourcePolicy' = 'x_response' THEN 'x'
                         ELSE 'website'
                       END = %s
                  )
                """,
                (args.lane, args.lane),
            )
            recovered = cursor.rowcount
    close_pool()
    print(f"Recovered {recovered} interrupted {args.lane} article job(s).")


if __name__ == "__main__":
    main()
