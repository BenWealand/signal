from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.llm import zen_writer
from app.processing import article_writer


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ZenPromptFallbackTest(unittest.TestCase):
    def test_prompt_variants_start_with_original_and_add_closer_angles(self):
        with patch.object(article_writer.queries, "list_trending_topics", return_value=[]):
            variants = article_writer._prompt_variants("technology")
        self.assertEqual(variants[0], "technology")
        self.assertGreater(len(variants), 3)
        self.assertTrue(any("latest developments" in item for item in variants))

    def test_zen_403_falls_back_to_free_model(self):
        original_settings = zen_writer.settings
        original_last_429 = zen_writer._last_429_at
        zen_writer.settings = SimpleNamespace(
            opencode_api_key="key",
            opencode_model="deepseek-v4-flash",
            opencode_fast_model="deepseek-v4-flash",
        )
        zen_writer._last_429_at = 0.0
        zen_writer._call_times.clear()
        models: list[str] = []
        auth_headers: list[dict] = []

        package = {
            "headline": "Senate Passes Budget Bill Overnight",
            "dek": "Lawmakers approved the package after a late floor fight.",
            "body": [
                "First paragraph with enough detail for validation across the overnight senate vote.",
                "Second paragraph confirming the sourced outcome from multiple public outlets covering the bill.",
            ],
        }
        ok_body = json.dumps({"choices": [{"message": {"content": json.dumps(package)}}]}).encode("utf-8")

        def fake_urlopen(req, timeout=30):
            payload = json.loads(req.data.decode("utf-8"))
            model = payload.get("model")
            models.append(model)
            auth_headers.append(dict(req.headers))
            # Fail the primary model hard; succeed on the first failover model.
            if model == "deepseek-v4-flash":
                err = json.dumps({"error": {"message": "model disabled", "type": "permission_error"}}).encode("utf-8")
                raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(err))
            return _FakeResponse(ok_body)

        try:
            with patch.object(zen_writer.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = zen_writer.write_article_package_with_zen(
                    "senate budget",
                    [{"source_name": "AP", "title": "Budget vote", "raw_text": "Details. " * 80}],
                    mode="fast",
                )
        finally:
            zen_writer.settings = original_settings
            zen_writer._last_429_at = original_last_429
            zen_writer._call_times.clear()

        self.assertIsNotNone(result)
        self.assertEqual(result["headline"], "Senate Passes Budget Bill Overnight")
        self.assertEqual(models[0], "deepseek-v4-flash")
        self.assertIn("minimax-m2.7", models)
        header_blob = " ".join(f"{k}:{v}" for k, v in auth_headers[0].items()).lower()
        self.assertIn("authorization", header_blob)
        self.assertIn("x-api-key", header_blob)

    def test_write_selects_closer_prompt_before_generation(self):
        calls: list[str] = []

        def fake_fast(prompt, **_kwargs):
            calls.append(prompt)
            return {
                "id": "write-1",
                "prompt": prompt,
                "headline": "AI Chip Export Rules Tighten",
                "body": ["One paragraph.", "Two paragraph."],
                "generation_mode": "fast",
            }

        with (
            patch.object(article_writer, "_fast_article_from_prompt", side_effect=fake_fast),
            patch.object(
                article_writer,
                "_select_supported_variant",
                return_value=(
                    "artificial intelligence semiconductor technology cybersecurity",
                    [
                        {"url": "https://a.example/story"},
                        {"url": "https://b.example/story"},
                        {"url": "https://c.example/story"},
                        {"url": "https://d.example/story"},
                    ],
                ),
            ),
            patch.object(
                article_writer.queries,
                "find_recent_generated_article_by_fingerprint",
                return_value={},
            ),
        ):
            article = article_writer.write_article_from_prompt("technology", mode="fast")

        self.assertEqual(len(calls), 1)
        self.assertIn("artificial intelligence", calls[0])
        self.assertEqual(article["prompt"], "technology")
        self.assertTrue(article.get("promptAdjusted"))
        self.assertIn("artificial intelligence", article.get("resolvedPrompt", ""))


if __name__ == "__main__":
    unittest.main()
