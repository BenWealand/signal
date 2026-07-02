from __future__ import annotations

from pathlib import Path
from typing import Any


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
INITIAL_VERSION = "0001_initial_schema"


def _split_sql(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def ensure_migrations_table(cur: Any) -> None:
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )


def applied_versions(cur: Any) -> set[str]:
    ensure_migrations_table(cur)
    cur.execute("SELECT version FROM schema_migrations")
    versions = set()
    for row in cur.fetchall():
        version = row["version"] if isinstance(row, dict) else row[0]
        versions.add(str(version))
    return versions


def apply_migrations(cur: Any, schema_path: Path) -> None:
    seen = applied_versions(cur)
    if INITIAL_VERSION not in seen:
        for statement in _split_sql(schema_path.read_text(encoding="utf-8")):
            cur.execute(statement)
        cur.execute("INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING", (INITIAL_VERSION,))
        seen.add(INITIAL_VERSION)

    if not MIGRATIONS_DIR.exists():
        return

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in seen:
            continue
        for statement in _split_sql(path.read_text(encoding="utf-8")):
            cur.execute(statement)
        cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
