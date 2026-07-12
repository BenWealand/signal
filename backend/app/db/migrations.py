from __future__ import annotations

from pathlib import Path
from typing import Any


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
INITIAL_VERSION = "0001_initial_schema"


def _split_sql(sql: str) -> list[str]:
    """Split SQL on semicolons while respecting dollar-quoted and string literals."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(sql)
    in_single = False
    dollar_tag: str | None = None

    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if dollar_tag is not None:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(ch)
            i += 1
            continue

        if in_single:
            buf.append(ch)
            if ch == "'" and nxt == "'":
                buf.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue

        if ch == "$":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                dollar_tag = sql[i : j + 1]
                buf.append(dollar_tag)
                i = j + 1
                continue

        if ch == "-" and nxt == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue

        if ch == ";":
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    trailing = "".join(buf).strip()
    if trailing:
        statements.append(trailing)
    return statements


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
