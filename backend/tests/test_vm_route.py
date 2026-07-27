from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api import routes_vm
from app.api.routes_vm import VMPost
from app.llm import gemini_writer
from app.x.models import XSharePackage


class VMRoutingTests(unittest.TestCase):
    def test_vm_returns_admin_x_intent_url(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        intent_url = "https://x.com/intent/tweet?text=Draft"
        package = XSharePackage(
            status="ready_to_post",
            article_url="https://signal.example/article/write-1",
            reply_text="Draft",
            share={"intentUrl": intent_url},
        )

        with (
            patch.object(routes_vm, "_check_article_rate_limit"),
            patch.object(
                routes_vm,
                "generic_news_prompt_from_x_posts_with_gemini",
                return_value="Berlin parade vehicle attack investigation",
            ) as generalize,
            patch.object(routes_vm, "write_article_for_candidate", return_value=package) as write,
        ):
            result = routes_vm.create_vm_draft(
                request,
                [VMPost(url="https://x.com/example/status/1", text="Breaking event update")],
            )

        self.assertEqual(result, {"url": intent_url})
        generalize.assert_called_once()
        candidate = write.call_args.args[0]
        self.assertEqual(candidate.prompt, "Berlin parade vehicle attack investigation")
        self.assertEqual(candidate.provider, "manual-prompt")
        self.assertEqual(write.call_args.kwargs["mode"], "fast")

    def test_vm_rejects_posts_without_text(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        with patch.object(routes_vm, "_check_article_rate_limit"):
            with self.assertRaises(Exception) as raised:
                routes_vm.create_vm_draft(
                    request,
                    [VMPost(url="https://x.com/example/status/1", text="")],
                )
        self.assertEqual(raised.exception.status_code, 422)


class VMGeminiPromptTests(unittest.TestCase):
    @patch.object(gemini_writer, "_rate_limited", return_value=False)
    @patch.object(gemini_writer.urllib.request, "urlopen")
    def test_gemini_generalizes_posts_to_news_prompt(self, urlopen, _rate_limited):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "candidates": [{
                        "content": {
                            "parts": [{
                                "text": json.dumps({
                                    "prompt": "Marvel Studios Ghost Rider Ryan Gosling announcement",
                                }),
                            }],
                        },
                    }],
                }).encode("utf-8")

        urlopen.return_value = FakeResponse()
        with patch.object(
            gemini_writer,
            "settings",
            SimpleNamespace(
                gemini_api_key="test-key",
                gemini_fast_model="gemini-flash-lite-latest",
                gemini_model="gemini-flash-latest",
            ),
        ):
            result = gemini_writer.generic_news_prompt_from_x_posts_with_gemini([
                {
                    "url": "https://x.com/MarvelStudios/status/1",
                    "text": "Ryan Gosling will star in Marvel Studios' Ghost Rider.",
                },
            ])
        self.assertEqual(result, "Marvel Studios Ghost Rider Ryan Gosling announcement")

    @patch.object(gemini_writer, "_rate_limited", return_value=False)
    @patch.object(gemini_writer, "_record_429")
    @patch.object(gemini_writer.urllib.request, "urlopen")
    def test_gemini_prompt_retries_alternate_model(self, urlopen, record_429, _rate_limited):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "candidates": [{
                        "content": {
                            "parts": [{"text": '{"prompt":"Federal Reserve interest rate decision"}'}],
                        },
                    }],
                }).encode("utf-8")

        urlopen.side_effect = [
            urllib.error.HTTPError("https://example", 429, "quota", {}, None),
            FakeResponse(),
        ]
        with patch.object(
            gemini_writer,
            "settings",
            SimpleNamespace(
                gemini_api_key="test-key",
                gemini_fast_model="gemini-flash-lite-latest",
                gemini_model="gemini-flash-latest",
            ),
        ):
            result = gemini_writer.generic_news_prompt_from_x_posts_with_gemini([
                {"url": "https://x.com/example/status/1", "text": "Fed decision update"},
            ])

        self.assertEqual(result, "Federal Reserve interest rate decision")
        self.assertEqual(urlopen.call_count, 2)
        record_429.assert_called_once()


if __name__ == "__main__":
    unittest.main()
