from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.connection import create_tables
from app.db.queries import replace_sources
from app.ingest.source_registry import DEFAULT_SOURCES


if __name__ == "__main__":
    create_tables()
    replace_sources(DEFAULT_SOURCES)
    print(f"Seeded {len(DEFAULT_SOURCES)} trusted source records.")

