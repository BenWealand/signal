from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.processing.article_writer import write_article_from_prompt


def source(url: str, title: str, text: str, *, name: str = "Outlet") -> dict:
    return {
        "source_name": name,
        "domain": url.split("/")[2],
        "title": title,
        "url": url,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "description": text[:200],
        "raw_text": text,
        "topic": "senate budget vote",
        "language": "en",
        "status": "new",
    }


class ArticleWriterQualityTest(unittest.TestCase):
    @patch("app.processing.article_writer.queries.save_generated_article", return_value="saved")
    @patch("app.processing.article_writer._cached_articles_for_prompt", return_value=[])
    @patch("app.processing.article_writer.fetch_gdelt_articles")
    @patch("app.processing.article_writer.fetch_articles_for_query")
    def test_fast_mode_returns_source_metadata_and_lightweight_consensus(
        self,
        fetch_rss,
        fetch_gdelt,
        _cached,
        _save,
    ):
        text = "The Senate passed the budget bill by a 54-46 vote. " * 6
        fetch_rss.return_value = [
            source("https://reuters.com/world/us/budget", "Senate passes budget bill by 54-46 vote", text, name="Reuters"),
            source("https://apnews.com/article/budget", "Senate passes budget bill by 54-46 vote", text, name="AP"),
        ]
        fetch_gdelt.return_value = [
            source("https://bbc.com/news/budget", "Senate passes budget bill by 54-46 vote", text, name="BBC"),
        ]

        article = write_article_from_prompt("latest senate budget vote", mode="fast", use_gemini=False)

        self.assertEqual(article["generation_mode"], "fast")
        self.assertTrue(article["used_live_sources"])
        self.assertIn(article["consensus_level"], {"moderate", "strong"})
        self.assertGreaterEqual(article["source_quality"]["usable_source_count"], 2)
        self.assertTrue(article["consensus"])
        self.assertIn("scoreMetadata", article)

    @patch("app.processing.article_writer.queries.save_generated_article", return_value="saved")
    @patch("app.processing.article_writer._cached_articles_for_prompt", return_value=[])
    @patch("app.processing.article_writer.fetch_gdelt_articles", return_value=[])
    @patch("app.processing.article_writer.fetch_articles_for_query")
    def test_thorough_mode_returns_transparent_quality_gate_fallback(
        self,
        fetch_rss,
        _gdelt,
        _cached,
        _save,
    ):
        fetch_rss.return_value = [
            source("https://reuters.com/world/us/budget", "Senate budget vote latest update", "The Senate budget vote is developing. " * 5, name="Reuters"),
            source("https://apnews.com/article/budget", "Senate budget vote latest update", "The Senate budget vote is developing. " * 5, name="AP"),
        ]

        article = write_article_from_prompt("latest senate budget vote", mode="thorough", use_gemini=False)

        self.assertEqual(article["generation_mode"], "thorough")
        self.assertEqual(article["fallback_reason"], "quality_gate_failed")
        self.assertEqual(article["consensus_level"], "none")
        self.assertIn("minimum_usable_source_count", article["source_quality"]["failed_gates"])


if __name__ == "__main__":
    unittest.main()
