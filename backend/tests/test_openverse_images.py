from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingest import openverse_images as image_module
from app.ingest.openverse_images import find_openverse_image


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

    @patch("app.ingest.openverse_images.urllib.request.urlopen")
    def test_returns_relevant_open_image_with_attribution(self, urlopen):
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

    @patch("app.ingest.openverse_images.urllib.request.urlopen")
    def test_rejects_unrelated_or_non_attributable_results(self, urlopen):
        missing_creator = image_result("Federal Reserve building", creator="")
        unrelated = image_result("Coastal mountain range", license_code="cc0")
        urlopen.return_value = FakeResponse({"results": [missing_creator, unrelated]})

        self.assertEqual(find_openverse_image("Federal Reserve interest rates"), {})

    @patch("app.ingest.openverse_images.urllib.request.urlopen", side_effect=TimeoutError)
    def test_provider_failure_does_not_raise(self, _urlopen):
        with patch("app.ingest.openverse_images.logger.warning") as warning:
            self.assertEqual(find_openverse_image("Supreme Court ethics rules"), {})
        warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
