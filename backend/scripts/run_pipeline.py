from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.connection import create_tables
from app.processing.pipeline import run_pipeline


def main() -> None:
    create_tables()
    results = run_pipeline()
    for result in results:
        print(f"Story: {result['topic_label']}")
        print()
        print("Summary:")
        print(result["summary"])
        print()
        print("Supported claims:")
        for claim in result["supported_claims"]:
            print(f"- {claim['claim_text']} ({claim['support_count']} sources)")
        print()
        print("Sources:")
        for source in result["sources"]:
            print(f"- {source}")
        print()


if __name__ == "__main__":
    main()

