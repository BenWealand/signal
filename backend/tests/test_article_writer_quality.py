from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.processing.article_writer import (
    ZenArticleUnavailable,
    _article_body,
    write_article_from_prompt,
)


ARTICLE_IMAGE = {
    "url": "https://images.example.com/senate.jpg",
    "title": "United States Capitol",
    "creator": "Example Photographer",
    "license": "CC0",
    "licenseUrl": "https://creativecommons.org/publicdomain/zero/1.0/",
    "sourceUrl": "https://example.com/senate-image",
    "provider": "Openverse",
}


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
    def test_provider_outage_uses_attributed_source_digest(self):
        sources = [
            source(
                "https://reuters.com/world/us/budget",
                "Senate approves budget package after overnight vote",
                "The Senate approved the budget package after an overnight vote. "
                "Lawmakers debated spending provisions before the final roll call. " * 3,
                name="Reuters",
            ),
            source(
                "https://apnews.com/article/budget",
                "Budget legislation advances following Senate debate",
                "The budget legislation advanced following Senate debate. "
                "The measure now moves to the next stage of the legislative process. " * 3,
                name="AP",
            ),
        ]
        with (
            patch("app.llm.zen_writer.write_article_package_with_zen", return_value=None),
            patch(
                "app.llm.zen_writer.describe_last_zen_error",
                return_value="Article providers are temporarily unavailable.",
            ),
        ):
            body, header = _article_body(
                "senate budget vote",
                sources,
                [],
                [],
                require_zen=True,
            )

        self.assertGreaterEqual(len(body), 2)
        self.assertTrue(any("Reuters" in paragraph for paragraph in body))
        self.assertTrue(any("AP" in paragraph for paragraph in body))
        self.assertIsNone(header)

    @patch("app.llm.zen_writer._api_key", return_value="test-key")
    @patch("app.ingest.openverse_images.find_openverse_image", return_value=ARTICLE_IMAGE)
    @patch("app.processing.article_writer.queries.save_generated_article", return_value="saved")
    @patch("app.llm.zen_writer.write_article_package_with_zen")
    @patch("app.processing.article_writer._cached_articles_for_prompt", return_value=[])
    @patch("app.processing.article_writer.fetch_gdelt_articles")
    @patch("app.processing.article_writer.fetch_articles_for_query_fast")
    def test_fast_mode_requires_zen_draft(
        self,
        fetch_rss,
        fetch_gdelt,
        _cached,
        write_zen,
        _save,
        find_image,
        _api_key,
    ):
        text = "The Senate passed the budget bill by a 54-46 vote. " * 6
        zen_body = (
            "Zen wrote the first sourced draft paragraph with enough detail to pass validation.\n\n"
            "Zen wrote the second sourced draft paragraph from the supplied public articles."
        )
        write_zen.return_value = {
            "headline": "Senate Passes Budget Bill By Narrow Margin",
            "dek": "Lawmakers advanced the measure after a late-night floor vote.",
            "body": zen_body,
        }
        fetch_rss.return_value = [
            source("https://reuters.com/world/us/budget", "Senate passes budget bill by 54-46 vote", text, name="Reuters"),
            source("https://apnews.com/article/budget", "Senate passes budget bill by 54-46 vote", text, name="AP"),
        ]
        fetch_gdelt.return_value = [
            source("https://bbc.com/news/budget", "Senate passes budget bill by 54-46 vote", text, name="BBC"),
        ]

        article = write_article_from_prompt("latest senate budget vote", mode="fast", use_zen=False)

        self.assertEqual(article["generation_mode"], "fast")
        self.assertEqual(article["body"], zen_body.split("\n\n"))
        self.assertEqual(article["headline"], "Senate Passes Budget Bill By Narrow Margin")
        self.assertTrue(article["used_live_sources"])
        self.assertIn(article["consensus_level"], {"moderate", "strong"})
        self.assertGreaterEqual(article["source_quality"]["usable_source_count"], 2)
        self.assertTrue(article["consensus"])
        self.assertIn("scoreMetadata", article)
        self.assertEqual(article["image"], ARTICLE_IMAGE)
        write_zen.assert_called_once()
        self.assertEqual(write_zen.call_args.kwargs.get("mode"), "fast")
        self.assertTrue(callable(write_zen.call_args.kwargs.get("on_chunk")))
        find_image.assert_called()
        image_topic = find_image.call_args.kwargs.get("topic") or find_image.call_args.args[0]
        self.assertIn("Senate Passes Budget Bill", image_topic)
        self.assertIn("Zen wrote the first sourced draft paragraph", image_topic)

    @patch("app.llm.zen_writer._api_key", return_value="test-key")
    @patch("app.ingest.openverse_images.find_openverse_image", return_value={})
    @patch("app.processing.article_writer.queries.save_generated_article", return_value="saved")
    @patch("app.llm.zen_writer.write_article_package_with_zen")
    @patch("app.processing.article_writer.fetch_gdelt_articles")
    @patch("app.processing.article_writer.fetch_articles_for_query_fast")
    @patch("app.processing.article_writer._cached_articles_for_prompt")
    def test_fast_mode_prefers_desk_cache_before_live_fetch(
        self,
        cached,
        fetch_rss,
        fetch_gdelt,
        write_zen,
        _save,
        find_image,
        _api_key,
    ):
        text = "Cabinet officials briefed lawmakers on the semiconductor export controls. " * 5
        cached.return_value = [
            source("https://reuters.com/tech/chips", "Semiconductor export controls tighten", text, name="Reuters"),
            source("https://apnews.com/article/chips", "Semiconductor export controls tighten", text, name="AP"),
            source("https://bbc.com/news/chips", "Semiconductor export controls tighten", text, name="BBC"),
            source("https://theguardian.com/chips", "Semiconductor export controls tighten", text, name="Guardian"),
        ]
        write_zen.return_value = {
            "headline": "Export Controls Tighten Around Chip Tools",
            "dek": "Multiple outlets reported the same cabinet briefing details.",
            "body": "First paragraph from cache sources.\n\nSecond paragraph confirming the briefing.",
        }

        article = write_article_from_prompt("semiconductor export controls", mode="fast")

        self.assertEqual(article["generation_mode"], "fast")
        self.assertFalse(article["used_live_sources"])
        fetch_rss.assert_not_called()
        find_image.assert_called()
        image_topic = find_image.call_args.kwargs.get("topic") or find_image.call_args.args[0]
        self.assertIn("Export Controls Tighten Around Chip Tools", image_topic)
        fetch_gdelt.assert_not_called()
        write_zen.assert_called_once()

    @patch("app.processing.article_writer._desk_rescue_zen_article", side_effect=ZenArticleUnavailable("desk rescue blocked in test"))
    @patch("app.processing.article_writer.queries.list_trending_topics", return_value=[])
    @patch("app.llm.zen_writer._api_key", return_value="test-key")
    @patch("app.processing.article_writer.queries.save_generated_article", return_value="saved")
    @patch("app.processing.article_writer._cached_articles_for_prompt", return_value=[])
    @patch("app.processing.article_writer.fetch_gdelt_articles", return_value=[])
    @patch("app.processing.article_writer.fetch_articles_for_query_fast")
    def test_thorough_mode_does_not_save_quality_gate_fallback(
        self,
        fetch_rss,
        _gdelt,
        _cached,
        save_generated,
        _api_key,
        _topics,
        _desk_rescue,
    ):
        fetch_rss.return_value = [
            source("https://reuters.com/world/us/budget", "Senate budget vote latest update", "The Senate budget vote is developing. " * 5, name="Reuters"),
            source("https://apnews.com/article/budget", "Senate budget vote latest update", "The Senate budget vote is developing. " * 5, name="AP"),
        ]

        with self.assertRaises(ZenArticleUnavailable):
            write_article_from_prompt("latest senate budget vote", mode="thorough", use_zen=False)
        save_generated.assert_not_called()


if __name__ == "__main__":
    unittest.main()
