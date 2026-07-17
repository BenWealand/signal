from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingest import openverse_images as image_module
from app.ingest.openverse_images import (
    candidate_title_relevance,
    find_openverse_image,
    priority_image_queries,
)


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def image_result(
    title: str,
    *,
    creator: str = "Jane Photographer",
    license_code: str = "by",
    tags: list[dict] | None = None,
) -> dict:
    return {
        "title": title,
        "creator": creator,
        "creator_url": "https://example.com/creator",
        "license": license_code,
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "foreign_landing_url": "https://example.com/image-page",
        "thumbnail": "https://images.example.com/photo.jpg",
        "url": "https://images.example.com/original.jpg",
        "width": 1600,
        "height": 900,
        "tags": tags if tags is not None else [{"name": "central bank"}],
    }


class OpenverseImagesTest(unittest.TestCase):
    def setUp(self):
        image_module._image_cache.clear()

    def test_priority_image_queries_prefer_people_then_places(self):
        entities = [
            {"text": "Washington", "type": "GPE"},
            {"text": "Federal Reserve", "type": "ORG"},
            {"text": "Jerome Powell", "type": "PERSON"},
            {"text": "March 15", "type": "DATE"},
        ]
        with patch("app.ingest.openverse_images.extract_entities", return_value=entities):
            queries = priority_image_queries(
                "Jerome Powell spoke at the Federal Reserve in Washington on March 15"
            )

        self.assertEqual(queries[0], '"Jerome Powell"')
        self.assertEqual(queries[1], '"Federal Reserve"')
        self.assertTrue(any("Washington" in q and "flag" in q.lower() for q in queries))
        self.assertNotIn("Washington", queries)
        self.assertIn('"March 15"', queries)

    def test_expands_bare_country_into_concrete_sports_queries(self):
        entities = [{"text": "Spain", "type": "GPE"}]
        article = "Spain faces Argentina in the FIFA World Cup final after the semi-final."
        with patch("app.ingest.openverse_images.extract_entities", return_value=entities):
            queries = priority_image_queries(article)
            preferred = image_module.normalize_image_search_subjects(["Spain"], article)

        self.assertTrue(any("flag" in q.lower() for q in queries))
        self.assertTrue(any("football" in q.lower() or "team" in q.lower() for q in queries))
        self.assertNotIn("Spain", queries)
        self.assertNotIn('"Spain"', queries)
        self.assertEqual(preferred, queries[: len(preferred)])
        self.assertTrue(any("flag" in q.lower() for q in preferred))

    def test_title_relevance_rejects_offtopic_league_photo(self):
        article = (
            "English Football League Playoff Finals Conclude as Premier League "
            "Golden Boot Finalized"
        )
        article_keywords = image_module._keywords(article)
        bad = image_result(
            "Lingerie League",
            tags=[{"name": "football"}, {"name": "league"}],
        )
        good = image_result(
            "English Football League playoff final at Wembley",
            tags=[{"name": "soccer"}],
        )

        self.assertLess(candidate_title_relevance(bad, article_keywords, article_text=article), 0)
        self.assertGreater(candidate_title_relevance(good, article_keywords, article_text=article), 0)

    def test_exact_entity_in_title_accepts_filler_words(self):
        cases = [
            (
                "Keir Starmer met European leaders after talks on Ukraine support.",
                [{"text": "Keir Starmer", "type": "PERSON"}],
                "Official portrait of Keir Starmer crop 2",
            ),
            (
                "Federal Reserve officials held interest rates steady after the latest meeting.",
                [{"text": "Federal Reserve", "type": "ORG"}],
                "Aerial view of the Federal Reserve building in Washington",
            ),
            (
                "Flood barriers rose along the Seine as Paris prepared for spring runoff.",
                [{"text": "Paris", "type": "GPE"}, {"text": "Seine", "type": "GPE"}],
                "Flood barriers on the Seine in Paris",
            ),
            (
                "Apple unveiled a thinner iPhone prototype during its spring product event.",
                [{"text": "iPhone", "type": "PRODUCT"}],
                "Close-up photo of an iPhone on a retail display table",
            ),
        ]
        for article, entities, title in cases:
            with self.subTest(title=title):
                with patch("app.ingest.openverse_images.extract_entities", return_value=entities):
                    score = candidate_title_relevance(
                        image_result(title),
                        image_module._keywords(article),
                        article_text=article,
                    )
                self.assertGreater(score, 0)

    def test_rejects_bare_country_title_for_sports_article(self):
        article = (
            "Spain and Argentina Prepare for 2026 FIFA World Cup Final in New Jersey. "
            "Spain faces Argentina in the World Cup final as questions emerge regarding "
            "Lamine Yamal's training status."
        )
        entities = [
            {"text": "Lamine Yamal", "type": "PERSON"},
            {"text": "Spain", "type": "GPE"},
            {"text": "Argentina", "type": "GPE"},
            {"text": "New Jersey", "type": "GPE"},
        ]
        with patch("app.ingest.openverse_images.extract_entities", return_value=entities):
            bare = candidate_title_relevance(
                image_result("Spain"),
                image_module._keywords(article),
                article_text=article,
            )
            player = candidate_title_relevance(
                image_result("Lamine Yamal training with Spain"),
                image_module._keywords(article),
                article_text=article,
            )
        self.assertLess(bare, 0)
        self.assertGreater(player, 0)

    def test_exact_entity_match_still_rejects_sensitive_offtopic_titles(self):
        article = "English Football League clubs prepared for the playoff finals."
        entities = [{"text": "English Football League", "type": "ORG"}]
        with patch("app.ingest.openverse_images.extract_entities", return_value=entities):
            score = candidate_title_relevance(
                image_result("Lingerie League"),
                image_module._keywords(article),
                article_text=article,
            )
        self.assertLess(score, 0)

    @patch("app.ingest.openverse_images.extract_entities", return_value=[
        {"text": "English Football League", "type": "ORG"},
    ])
    @patch("app.ingest.openverse_images.urllib.request.urlopen")
    def test_skips_title_mismatch_even_when_tags_overlap(self, urlopen, _entities):
        urlopen.return_value = FakeResponse({
            "results": [
                image_result(
                    "Lingerie League",
                    tags=[{"name": "football"}, {"name": "league"}, {"name": "final"}],
                ),
                image_result("Mountain sunset", tags=[{"name": "nature"}]),
            ]
        })

        image = find_openverse_image(
            "English Football League playoff finals Premier League golden boot"
        )

        self.assertEqual(image, {})

    @patch("app.ingest.openverse_images.extract_entities", return_value=[
        {"text": "Federal Reserve", "type": "ORG"},
    ])
    @patch("app.ingest.openverse_images.urllib.request.urlopen")
    def test_returns_relevant_open_image_with_attribution(self, urlopen, _entities):
        urlopen.return_value = FakeResponse({
            "results": [
                image_result("Mountain sunset"),
                image_result("Federal Reserve headquarters in Washington"),
            ]
        })

        image = find_openverse_image("Federal Reserve interest rates")

        self.assertEqual(image["title"], "Federal Reserve headquarters in Washington")
        self.assertEqual(image["creator"], "Jane Photographer")
        self.assertEqual(image["license"], "BY")
        self.assertEqual(image["provider"], "Openverse")
        request = urlopen.call_args.args[0]
        self.assertIn("license=", request.full_url)
        self.assertIn("mature=false", request.full_url)
        self.assertIn("%22Federal+Reserve%22", request.full_url)
        self.assertEqual(find_openverse_image("Federal Reserve interest rates"), image)
        urlopen.assert_called_once()

    @patch("app.ingest.openverse_images.extract_entities", return_value=[
        {"text": "Jerome Powell", "type": "PERSON"},
        {"text": "Federal Reserve", "type": "ORG"},
    ])
    @patch("app.ingest.openverse_images.urllib.request.urlopen")
    def test_searches_person_before_organization(self, urlopen, _entities):
        urlopen.side_effect = [
            FakeResponse({"results": []}),
            FakeResponse({"results": [image_result("Federal Reserve headquarters in Washington")]}),
        ]

        image = find_openverse_image("Jerome Powell Federal Reserve interest rates")

        self.assertEqual(image["title"], "Federal Reserve headquarters in Washington")
        self.assertEqual(urlopen.call_count, 2)
        first = urlopen.call_args_list[0].args[0].full_url
        second = urlopen.call_args_list[1].args[0].full_url
        self.assertIn("%22Jerome+Powell%22", first)
        self.assertIn("%22Federal+Reserve%22", second)

    @patch("app.ingest.openverse_images.extract_entities", return_value=[
        {"text": "English Football League", "type": "ORG"},
        {"text": "Premier League", "type": "ORG"},
    ])
    @patch("app.ingest.openverse_images.urllib.request.urlopen")
    def test_prefers_title_that_matches_article_subject(self, urlopen, _entities):
        urlopen.return_value = FakeResponse({
            "results": [
                image_result("Lingerie League", tags=[{"name": "football"}]),
                image_result("Premier League Golden Boot race", tags=[{"name": "soccer"}]),
            ]
        })

        image = find_openverse_image(
            "English Football League Playoff Finals Conclude as Premier League Golden Boot Finalized"
        )

        self.assertEqual(image["title"], "Premier League Golden Boot race")

    @patch("app.ingest.openverse_images.extract_entities", return_value=[
        {"text": "Federal Reserve", "type": "ORG"},
    ])
    @patch("app.ingest.openverse_images.urllib.request.urlopen")
    def test_rejects_unrelated_or_non_attributable_results(self, urlopen, _entities):
        missing_creator = image_result("Federal Reserve building", creator="")
        unrelated = image_result("Coastal mountain range", license_code="cc0")
        urlopen.return_value = FakeResponse({"results": [missing_creator, unrelated]})

        self.assertEqual(find_openverse_image("Federal Reserve interest rates"), {})

    @patch("app.ingest.openverse_images.extract_entities", return_value=[
        {"text": "Supreme Court", "type": "ORG"},
    ])
    @patch("app.ingest.openverse_images.urllib.request.urlopen", side_effect=TimeoutError)
    def test_provider_failure_does_not_raise(self, _urlopen, _entities):
        with patch("app.ingest.openverse_images.logger.warning") as warning:
            self.assertEqual(find_openverse_image("Supreme Court ethics rules"), {})
        warning.assert_called()

    @patch("app.ingest.openverse_images.find_openverse_image")
    def test_article_image_picker_uses_streamed_article_text(self, find_image):
        find_image.return_value = {
            "url": "https://images.example.com/wembley.jpg",
            "title": "English Football League playoff final at Wembley",
            "creator": "Example Photographer",
            "license": "BY",
        }
        picker = image_module.ArticleImagePicker(enabled=True, search_timeout=2.0, min_chars=40)
        picker.on_chunk({
            "headline": "English Football League Playoff Finals Conclude",
            "dek": "Promotions are settled across the leagues.",
            "draft_text": "Hull City secured promotion after the English Football League playoff final.",
        })
        image = picker.finalize(wait_seconds=1.0)

        self.assertEqual(image["title"], "English Football League playoff final at Wembley")
        find_image.assert_called()
        topic = find_image.call_args.kwargs.get("topic") or find_image.call_args.args[0]
        self.assertIn("English Football League Playoff Finals Conclude", topic)
        self.assertIn("Hull City secured promotion", topic)
        self.assertNotEqual(topic, "english football")

    @patch("app.ingest.openverse_images.find_openverse_image")
    def test_article_image_picker_finalize_after_hit_does_not_deadlock(self, find_image):
        find_image.return_value = {
            "url": "https://images.example.com/powell.jpg",
            "title": "Jerome Powell at the Federal Reserve",
            "creator": "Example Photographer",
            "license": "BY",
        }
        picker = image_module.ArticleImagePicker(enabled=True, search_timeout=2.0, min_chars=40)
        picker.on_chunk({
            "headline": "Powell Signals Steady Rates",
            "dek": "The Federal Reserve held its policy stance.",
            "draft_text": "Jerome Powell said the Federal Reserve would keep rates steady for now.",
        })
        # Ensure the background lookup finished so finalize takes the cached-hit path.
        for _ in range(50):
            if find_image.called:
                break
            __import__("time").sleep(0.02)
        image = picker.finalize(
            headline="Powell Signals Steady Rates",
            dek="The Federal Reserve held its policy stance.",
            body="Jerome Powell said the Federal Reserve would keep rates steady for now.",
            wait_seconds=1.0,
        )
        self.assertEqual(image["title"], "Jerome Powell at the Federal Reserve")

    @patch(
        "app.llm.gemini_writer.suggest_image_queries_with_gemini",
        return_value=["Lamine Yamal Spain", "Argentina World Cup final"],
    )
    @patch("app.ingest.openverse_images.find_openverse_image")
    def test_finalize_uses_gemini_people_first_queries(self, find_image, _suggest):
        find_image.side_effect = [
            {},
            {
                "url": "https://images.example.com/yamal.jpg",
                "title": "Lamine Yamal Spain",
                "creator": "Example Photographer",
                "license": "BY",
            },
        ]
        picker = image_module.ArticleImagePicker(enabled=True, search_timeout=2.0, min_chars=40)
        picker.on_chunk({
            "headline": "Spain and Argentina Prepare for World Cup Final",
            "dek": "Questions emerge regarding Lamine Yamal's training status.",
            "draft_text": "Spain faces Argentina after the semi-final in Atlanta.",
        })
        for _ in range(50):
            if find_image.called:
                break
            __import__("time").sleep(0.02)
        image = picker.finalize(
            headline="Spain and Argentina Prepare for World Cup Final",
            dek="Questions emerge regarding Lamine Yamal's training status.",
            body=["Spain faces Argentina after the semi-final in Atlanta."],
            wait_seconds=1.0,
        )

        self.assertEqual(image["title"], "Lamine Yamal Spain")
        final_call = find_image.call_args_list[-1]
        self.assertEqual(
            final_call.kwargs.get("preferred_queries"),
            ["Lamine Yamal Spain", "Argentina World Cup final"],
        )


if __name__ == "__main__":
    unittest.main()
