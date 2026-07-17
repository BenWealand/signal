from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db import queries


class FakeCursor:
    def __init__(self):
        self.executed: list[tuple[str, tuple | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql: str, params=None):
        self.executed.append((sql, params))


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


class GeneratedArticleImagePersistenceTest(unittest.TestCase):
    def test_save_serializes_image_metadata_with_article(self):
        cursor = FakeCursor()
        image = {
            "url": "https://images.example.com/fed.jpg",
            "creator": "Jane Photographer",
            "license": "BY",
        }
        article = {
            "id": "write-image-1",
            "source": "Signal desk",
            "tag": "prompt",
            "trendUrl": "",
            "prompt": "Federal Reserve rates",
            "headline": "Federal Reserve Holds Rates",
            "dek": "Officials announced their latest decision.",
            "summary": "Summary",
            "body": ["Paragraph one.", "Paragraph two."],
            "facts": [],
            "terms": ["federal", "reserve"],
            "sources": ["Example News"],
            "sourceLinks": [],
            "consensus": [],
            "sourceCount": 1,
            "deniedForBias": 0,
            "fairnessScore": 80,
            "accuracyScore": 80,
            "generation_mode": "fast",
            "used_live_sources": True,
            "section": "markets",
            "status": "published",
            "createdAt": "2026-07-17T12:00:00Z",
            "image": image,
        }

        with patch.object(queries, "get_connection", return_value=FakeConnection(cursor)):
            result = queries.save_generated_article(article)

        insert = next((params for sql, params in cursor.executed if "INSERT INTO generated_articles" in sql), None)
        self.assertEqual(result, article["id"])
        self.assertIsNotNone(insert)
        self.assertEqual(len(insert), 29)
        self.assertEqual(json.loads(insert[25]), image)


if __name__ == "__main__":
    unittest.main()
