from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg2
import psycopg2.extras

from app.config import settings


def _connect():
    return psycopg2.connect(settings.database_url, cursor_factory=psycopg2.extras.RealDictCursor)


@contextmanager
def get_connection() -> Iterator[psycopg2.extensions.connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_tables(schema_path: Path | None = None) -> None:
    path = schema_path or Path(__file__).with_name("schema.sql")
    sql = path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with get_connection() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
