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
        settings = SimpleNamespace(section_fast_articles_per_refresh=3, section_fast_min_age_minutes=45)

        with patch.object(routes_news, "settings", settings), \
             patch.object(routes_news.queries, "list_section_generation_prompts", return_value=prompts), \
             patch.object(routes_news.queries, "generated_prompt_exists_recent", return_value=False), \
             patch.object(routes_news.queries, "enqueue_article_generation_job") as enqueue, \
             patch.object(routes_news.cache, "invalidate"):
            routes_news._generate_fast_section_articles("markets")

        self.assertEqual(enqueue.call_count, 3)
        self.assertTrue(all(call.kwargs["mode"] == "fast" for call in enqueue.call_args_list))
        queued_sections = [call.kwargs["payload"]["section"] for call in enqueue.call_args_list]
        self.assertEqual(queued_sections, ["markets", "markets", "markets"])

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
             patch.object(routes_news.queries, "enqueue_article_generation_job") as enqueue, \
             patch.object(routes_news.cache, "invalidate"):
            routes_news._generate_fast_section_articles("world")

        self.assertEqual(enqueue.call_count, 2)

    def test_section_prompts_skip_broad_keyword_bags(self):
        with patch.object(
            routes_news.queries,
            "list_section_generation_prompts",
            return_value=[
                "stock market economy financial inflation interest rates",
                "Jerome Powell signals steady Federal Reserve policy path",
                "climate change environment renewable energy weather",
            ],
        ):
            prompts = routes_news._section_prompts("markets", 5)

        self.assertEqual(prompts, ["Jerome Powell signals steady Federal Reserve policy path"])


if __name__ == "__main__":
    unittest.main()
