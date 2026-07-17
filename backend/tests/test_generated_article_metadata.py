from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.queries import _decode_generated_article


class GeneratedArticleMetadataTest(unittest.TestCase):
    def test_decodes_persisted_source_transparency_fields(self):
        decoded = _decode_generated_article({
            "id": "a1",
            "source": "Signal desk",
            "tag": "prompt",
            "trend_url": "",
            "prompt": "senate budget vote",
            "headline": "Senate Budget Vote",
            "dek": "dek",
            "summary": "summary",
            "body": '["body"]',
            "facts": '[]',
            "terms": '["senate"]',
            "sources": '["Reuters"]',
            "source_links": '[{"source":"Reuters","url":"https://reuters.com/a"}]',
            "consensus": '[{"status":"supported"}]',
            "source_count": 1,
            "denied_for_bias": 0,
            "fairness_score": 72,
            "accuracy_score": 75,
            "score_metadata": '{"accuracyScore":"heuristic"}',
            "generation_mode": "fast",
            "source_quality": '{"level":"limited"}',
            "consensus_level": "moderate",
            "used_live_sources": 1,
            "fallback_reason": "",
            "image": '{"url":"https://images.example.com/fed.jpg","license":"CC0"}',
            "status": "published",
            "created_at": "2026-05-29T12:00:00Z",
        })

        self.assertEqual(decoded["generation_mode"], "fast")
        self.assertEqual(decoded["source_quality"]["level"], "limited")
        self.assertEqual(decoded["sourceLinks"][0]["source"], "Reuters")
        self.assertEqual(decoded["consensus"][0]["status"], "supported")
        self.assertTrue(decoded["used_live_sources"])
        self.assertIn("accuracyScore", decoded["scoreMetadata"])
        self.assertEqual(decoded["image"]["license"], "CC0")


if __name__ == "__main__":
    unittest.main()
