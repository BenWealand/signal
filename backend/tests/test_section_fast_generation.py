from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api import routes_news


class SectionFastGenerationTest(unittest.TestCase):
    def test_section_refresh_generates_shared_fast_articles(self):
        prompts = [
            "Central bank rate path draws market reaction",
            "Regional banks face renewed commercial property pressure",
            "Oil prices shift after shipping disruption",
        ]
        articles = []

        def fake_write(prompt, **kwargs):
            articles.append((prompt, kwargs))
            return {
                "id": f"article-{len(articles)}",
                "source": "Signal desk",
                "tag": "fast-draft",
                "prompt": prompt,
                "headline": prompt,
                "dek": "Fast draft",
                "summary": "Fast draft",
                "body": ["Fast draft body."],
                "facts": [],
                "terms": [],
                "sources": ["Source"],
                "sourceLinks": [],
                "consensus": [],
                "sourceCount": 1,
                "deniedForBias": 0,
                "fairnessScore": 80,
                "accuracyScore": 80,
                "generation_mode": "fast",
            }

        settings = SimpleNamespace(section_fast_articles_per_refresh=3, section_fast_min_age_minutes=45)

        with patch.object(routes_news, "settings", settings), \
             patch.object(routes_news.queries, "list_section_generation_prompts", return_value=prompts), \
             patch.object(routes_news.queries, "generated_prompt_exists_recent", return_value=False), \
             patch.object(routes_news, "write_article_from_prompt", side_effect=fake_write), \
             patch.object(routes_news.queries, "save_generated_article") as save_article, \
             patch.object(routes_news.cache, "invalidate"):
            routes_news._generate_fast_section_articles("markets")

        self.assertEqual(len(articles), 3)
        self.assertTrue(all(kwargs["mode"] == "fast" for _prompt, kwargs in articles))
        self.assertTrue(all(kwargs["use_gemini"] is True for _prompt, kwargs in articles))
        saved_sections = [call.args[0]["section"] for call in save_article.call_args_list]
        self.assertEqual(saved_sections, ["markets", "markets", "markets"])

    def test_section_refresh_skips_recent_duplicate_prompts(self):
        prompts = [
            "Duplicate topic",
            "Fresh topic one",
            "Fresh topic two",
        ]
        settings = SimpleNamespace(section_fast_articles_per_refresh=2, section_fast_min_age_minutes=45)

        with patch.object(routes_news, "settings", settings), \
             patch.object(routes_news.queries, "list_section_generation_prompts", return_value=prompts), \
             patch.object(routes_news.queries, "generated_prompt_exists_recent", side_effect=[True, False, False]), \
             patch.object(routes_news, "write_article_from_prompt", return_value={"id": "a", "prompt": "p"}), \
             patch.object(routes_news.queries, "save_generated_article") as save_article, \
             patch.object(routes_news.cache, "invalidate"):
            routes_news._generate_fast_section_articles("world")

        self.assertEqual(save_article.call_count, 2)


if __name__ == "__main__":
    unittest.main()
