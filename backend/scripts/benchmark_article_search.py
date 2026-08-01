#!/usr/bin/env python3
"""Benchmark cached article FTS and show the PostgreSQL execution nodes."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import close_pool, get_connection
from app.db.queries import search_articles_fts


VECTOR_SQL = """
  setweight(to_tsvector('english'::regconfig, COALESCE(title, '')), 'A') ||
  setweight(to_tsvector('english'::regconfig, COALESCE(description, '')), 'B') ||
  setweight(to_tsvector('english'::regconfig, COALESCE(topic, '')), 'B') ||
  setweight(to_tsvector('english'::regconfig, COALESCE(clean_text, '')), 'C')
"""


def plan_nodes(node: dict) -> list[dict]:
    return [node, *(child for plan in node.get("Plans", []) for child in plan_nodes(plan))]


def main() -> int:
    query = " OR ".join(sys.argv[1:]).strip() or '"United States" OR Ukraine OR tariffs'
    started = time.perf_counter()
    results = search_articles_fts(query, hours=48, limit=20)
    elapsed_ms = (time.perf_counter() - started) * 1000

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
                SELECT id
                FROM articles
                WHERE ({VECTOR_SQL}) @@ websearch_to_tsquery('english'::regconfig, %s)
                  AND duplicate_of IS NULL
                ORDER BY created_at DESC
                LIMIT 20
                """,
                (query,),
            )
            raw_plan = cur.fetchone()["QUERY PLAN"]
    close_pool()

    plan = raw_plan if isinstance(raw_plan, list) else json.loads(raw_plan)
    nodes = plan_nodes(plan[0]["Plan"])
    print(f"query={query!r} results={len(results)} application_ms={elapsed_ms:.2f}")
    for node in nodes:
        details = [node.get("Node Type", "")]
        if node.get("Index Name"):
            details.append(f"index={node['Index Name']}")
        details.append(f"rows={node.get('Actual Rows', 0)}")
        details.append(f"node_ms={node.get('Actual Total Time', 0):.3f}")
        print(" ".join(details))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
