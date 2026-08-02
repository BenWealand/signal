from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import psycopg2
import psycopg2.extras
import psycopg2.pool

from app.config import settings
from app.db.migrations import apply_migrations

_pool: psycopg2.pool.ThreadedConnectionPool | None = None

# psycopg2's pool raises immediately when every connection is checked out.
# Under a request burst plus background workers that turned transient
# contention into hard failures; wait briefly for a slot instead.
_POOL_WAIT_SECONDS = 10.0


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=max(2, settings.db_pool_max),
            dsn=settings.database_url,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool


def _acquire_connection(pool: psycopg2.pool.ThreadedConnectionPool):
    deadline = time.monotonic() + _POOL_WAIT_SECONDS
    while True:
        try:
            return pool.getconn()
        except psycopg2.pool.PoolError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


@contextmanager
def get_connection() -> Iterator[psycopg2.extensions.connection]:
    pool = _get_pool()
    conn = _acquire_connection(pool)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


def create_tables(schema_path: Path | None = None) -> None:
    path = schema_path or Path(__file__).with_name("schema.sql")
    with get_connection() as conn:
        with conn.cursor() as cur:
            apply_migrations(cur, path)
