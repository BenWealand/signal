#!/usr/bin/env python3
"""Apply schema.sql + numbered migrations (including 0003 auth roles)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import close_pool, create_tables, get_connection
from app.db.migrations import applied_versions


def main() -> int:
    create_tables()
    with get_connection() as conn:
        with conn.cursor() as cur:
            versions = sorted(applied_versions(cur))
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name IN ('role', 'email_confirmed', 'last_login_at')
                ORDER BY column_name
                """
            )
            cols = [row["column_name"] if isinstance(row, dict) else row[0] for row in cur.fetchall()]
    close_pool()
    print("Applied migrations:")
    for version in versions:
        print(f"  - {version}")
    print("users auth columns:", ", ".join(cols) if cols else "(missing)")
    required = {"email_confirmed", "last_login_at", "role"}
    if not required.issubset(set(cols)):
        print("ERROR: auth columns missing after migration", file=sys.stderr)
        return 1
    print("Auth migration ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
