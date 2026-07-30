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


def four_sources() -> list[dict]:
    text = "The Senate passed the budget bill by a 54-46 vote after an overnight debate. " * 8
    return [
        source("https://reuters.com/budget", "Senate passes budget bill", text, name="Reuters"),
        source("https://apnews.com/budget", "Budget advances in Senate", text, name="AP"),
        source("https://bbc.com/budget", "Senate approves budget measure", text, name="BBC"),
        source("https://theguardian.com/budget", "Budget vote concludes", text, name="Guardian"),
    ]


class ArticleWriterQualityTest(unittest.TestCase):
    def test_provider_outage_fails_without_source_digest(self):
        with patch(
            "app.processing.article_writer.generate_article_package",
            side_effect=RuntimeError("local writer unavailable"),
        ):
            with self.assertRaises(ZenArticleUnavailable) as ctx:
                _article_body("senate budget vote", four_sources(), [], [], require_zen=True)
        self.assertIn("local writer unavailable", str(ctx.exception))

    @patch("app.processing.article_writer.queries.find_recent_generated_article_by_fingerprint", return_value={})
    @patch("app.processing.article_writer._select_supported_variant")
    @patch("app.processing.article_writer.generate_article_package")
    def test_fast_mode_uses_one_complete_local_package(self, generate, select, _find):
        select.return_value = ("latest senate budget vote", four_sources())
        generate.return_value = {
            "headline": "Senate Passes Budget Bill By Narrow Margin",
            "dek": "Lawmakers advanced the measure after a late-night floor vote.",
            "body": ["A" * 100, "B" * 100, "C" * 100, "D" * 100],
        }
        article = write_article_from_prompt("latest senate budget vote", mode="fast")
        self.assertEqual(article["generation_mode"], "fast")
        self.assertEqual(article["headline"], "Senate Passes Budget Bill By Narrow Margin")
        self.assertEqual(article["image"], {})
        generate.assert_called_once()

    @patch("app.processing.article_writer.queries.find_recent_generated_article_by_fingerprint")
    @patch("app.processing.article_writer._select_supported_variant")
    def test_recent_source_fingerprint_reuses_article(self, select, find_recent):
        select.return_value = ("senate budget", four_sources())
        find_recent.return_value = {
            "id": "existing",
            "headline": "Existing article",
            "body": ["A" * 100] * 4,
        }
        article = write_article_from_prompt("senate budget", mode="fast", build_id="build-reuse")
        self.assertEqual(article["id"], "existing")
        self.assertTrue(article["_reused"])
        self.assertEqual(article["buildId"], "build-reuse")


if __name__ == "__main__":
    unittest.main()
