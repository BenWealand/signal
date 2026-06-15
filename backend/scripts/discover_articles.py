from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(script: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True)


if __name__ == "__main__":
    run("seed_sources.py")
    run("fetch_rss.py")
    run("fetch_gdelt.py")

