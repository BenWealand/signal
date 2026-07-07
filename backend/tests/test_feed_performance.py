from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import cache
from app.db.queries import _decode_feed_article, _filter_feed_articles


class FeedPerformanceTest(unittest.TestCase):
    def test_decode_feed_article_omits_heavy_fields(self):
        decoded = _decode_feed_article({
            "id": "a1",
            "source": "Signal desk",
            "tag": "prompt",
            "trend_url": "",
            "prompt": "senate budget vote",
            "headline": "Senate Budget Vote",
            "dek": "dek",
            "summary": "summary",
            "sources": '["Reuters"]',
            "source_count": 3,
            "denied_for_bias": 0,
            "fairness_score": 72,
            "accuracy_score": 75,
            "generation_mode": "fast",
            "used_live_sources": 1,
            "fallback_reason": "",
            "status": "published",
            "created_at": "2026-05-29T12:00:00Z",
        })

        self.assertTrue(decoded["preview"])
        self.assertEqual(decoded["headline"], "Senate Budget Vote")
        self.assertNotIn("body", decoded)
        self.assertNotIn("facts", decoded)
        self.assertNotIn("sourceLinks", decoded)

    def test_filter_feed_articles_respects_limit(self):
        items = [{"id": str(i), "prompt": f"topic {i}"} for i in range(5)]
        with patch("app.db.queries.article_is_blocked", return_value=Mock(blocked=False)):
            filtered = _filter_feed_articles(items, 2)
        self.assertEqual(len(filtered), 2)

    def test_cache_get_or_set_reuses_value_within_ttl(self):
        cache.invalidate()
        calls = {"count": 0}

        def factory():
            calls["count"] += 1
            return {"ok": True}

        first = cache.get_or_set("demo", 30, factory)
        second = cache.get_or_set("demo", 30, factory)
        self.assertEqual(first, second)
        self.assertEqual(calls["count"], 1)

    def test_cache_expires_after_ttl(self):
        cache.invalidate()
        calls = {"count": 0}

        def factory():
            calls["count"] += 1
            return calls["count"]

        cache.get_or_set("demo-expire", 0.05, factory)
        time.sleep(0.06)
        second = cache.get_or_set("demo-expire", 0.05, factory)
        self.assertEqual(second, 2)


if __name__ == "__main__":
    unittest.main()
