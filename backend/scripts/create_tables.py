from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.connection import create_tables


if __name__ == "__main__":
    create_tables()
    print("Created backend database tables.")

