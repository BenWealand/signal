from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingest import openverse_images as image_module
from app.ingest.openverse_images import find_openverse_image, priority_image_queries


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def image_result(title: str, *, creator: str = "Jane Photographer", license_code: str = "by") -> dict:
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
        "tags": [{"name": "central bank"}],
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

        self.assertEqual(
            queries,
            ['"Jerome Powell"', '"Federal Reserve"', "Washington", '"March 15"'],
        )

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


if __name__ == "__main__":
    unittest.main()
