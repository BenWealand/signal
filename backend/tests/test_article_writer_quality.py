from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.processing.article_writer import GeminiArticleUnavailable, write_article_from_prompt


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
    @patch("app.llm.gemini_writer.write_article_header_with_gemini", return_value=None)
    @patch("app.llm.gemini_writer.write_article_with_gemini")
    @patch("app.processing.article_writer._cached_articles_for_prompt", return_value=[])
    @patch("app.processing.article_writer.fetch_gdelt_articles")
    @patch("app.processing.article_writer.fetch_articles_for_query")
    def test_fast_mode_requires_gemini_draft(
        self,
        fetch_rss,
        fetch_gdelt,
        _cached,
        write_gemini,
        _write_header,
        _save,
    ):
        text = "The Senate passed the budget bill by a 54-46 vote. " * 6
        gemini_body = (
            "Gemini wrote the first sourced draft paragraph with enough detail to pass validation.\n\n"
            "Gemini wrote the second sourced draft paragraph from the supplied public articles."
        )
        write_gemini.return_value = gemini_body
        fetch_rss.return_value = [
            source("https://reuters.com/world/us/budget", "Senate passes budget bill by 54-46 vote", text, name="Reuters"),
            source("https://apnews.com/article/budget", "Senate passes budget bill by 54-46 vote", text, name="AP"),
        ]
        fetch_gdelt.return_value = [
            source("https://bbc.com/news/budget", "Senate passes budget bill by 54-46 vote", text, name="BBC"),
        ]

        article = write_article_from_prompt("latest senate budget vote", mode="fast", use_gemini=False)

        self.assertEqual(article["generation_mode"], "fast")
        self.assertEqual(article["body"], gemini_body.split("\n\n"))
        self.assertTrue(article["used_live_sources"])
        self.assertIn(article["consensus_level"], {"moderate", "strong"})
        self.assertGreaterEqual(article["source_quality"]["usable_source_count"], 2)
        self.assertTrue(article["consensus"])
        self.assertIn("scoreMetadata", article)
        write_gemini.assert_called_once()

    @patch("app.processing.article_writer.queries.save_generated_article", return_value="saved")
    @patch("app.processing.article_writer._cached_articles_for_prompt", return_value=[])
    @patch("app.processing.article_writer.fetch_gdelt_articles", return_value=[])
    @patch("app.processing.article_writer.fetch_articles_for_query")
    def test_thorough_mode_does_not_save_quality_gate_fallback(
        self,
        fetch_rss,
        _gdelt,
        _cached,
        save_generated,
    ):
        fetch_rss.return_value = [
            source("https://reuters.com/world/us/budget", "Senate budget vote latest update", "The Senate budget vote is developing. " * 5, name="Reuters"),
            source("https://apnews.com/article/budget", "Senate budget vote latest update", "The Senate budget vote is developing. " * 5, name="AP"),
        ]

        with self.assertRaises(GeminiArticleUnavailable):
            write_article_from_prompt("latest senate budget vote", mode="thorough", use_gemini=False)
        save_generated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
