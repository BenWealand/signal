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
from app.llm import zen_writer
from app.x.models import XSharePackage


class VMRoutingTests(unittest.TestCase):
    def test_vm_returns_reply_link_for_each_post(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        intent_urls = [
            "https://x.com/intent/tweet?text=Marvel&in_reply_to=101",
            "https://x.com/intent/tweet?text=Senate&in_reply_to=202",
        ]
        packages = [
            XSharePackage(
                status="ready_to_post",
                article_url="https://signal.example/article/write-1",
                reply_text="Marvel draft",
                share={"intentUrl": intent_urls[0]},
            ),
            XSharePackage(
                status="ready_to_post",
                article_url="https://signal.example/article/write-2",
                reply_text="Senate draft",
                share={"intentUrl": intent_urls[1]},
            ),
        ]
        posts = [
            VMPost(
                url="https://x.com/MarvelStudios/status/101",
                text="Black Panther announcement",
                reason="Official casting announcement",
                angle="Entertainment news",
                source_assessment="Primary source",
            ),
            VMPost(
                url="https://x.com/BasedMikeLee/status/202",
                text="Senate recess objection",
                reason="Senator announces procedural action",
                angle="Political procedure",
                source_assessment="Primary statement",
            ),
        ]

        with (
            patch.object(routes_vm, "_check_article_rate_limit"),
            patch.object(
                routes_vm,
                "generic_news_prompt_from_x_posts_with_zen",
                side_effect=[
                    "Black Panther 3 casting and release date",
                    "Senate August recess procedural dispute",
                ],
            ) as generalize,
            patch.object(
                routes_vm,
                "write_article_for_candidate",
                side_effect=packages,
            ) as write,
        ):
            result = routes_vm.create_vm_draft(request, posts)

        self.assertEqual(result, {
            "reply_links": [
                {"url": posts[0].url, "reply_url": intent_urls[0]},
                {"url": posts[1].url, "reply_url": intent_urls[1]},
            ],
        })
        self.assertEqual(generalize.call_count, 2)
        self.assertEqual(write.call_count, 2)
        first_candidate = write.call_args_list[0].args[0]
        second_candidate = write.call_args_list[1].args[0]
        self.assertEqual(first_candidate.post_id, "101")
        self.assertEqual(second_candidate.post_id, "202")
        self.assertEqual(first_candidate.provider, "manual-prompt")

    def test_vm_returns_partial_results_with_errors(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        package = XSharePackage(
            status="ready_to_post",
            article_url="https://signal.example/article/write-1",
            reply_text="Draft",
            share={"intentUrl": "https://x.com/intent/tweet?text=Draft&in_reply_to=1"},
        )
        with (
            patch.object(routes_vm, "_check_article_rate_limit"),
            patch.object(
                routes_vm,
                "generic_news_prompt_from_x_posts_with_zen",
                return_value="Federal Reserve interest rate decision",
            ),
            patch.object(routes_vm, "write_article_for_candidate", return_value=package),
        ):
            result = routes_vm.create_vm_draft(
                request,
                [
                    VMPost(url="https://x.com/example/status/1", text="Fed update"),
                    VMPost(url="https://example.com/not-x", text="Other update"),
                ],
            )
        self.assertEqual(len(result["reply_links"]), 1)
        self.assertEqual(result["errors"][0]["url"], "https://example.com/not-x")

    def test_vm_rejects_posts_without_text(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        with patch.object(routes_vm, "_check_article_rate_limit"):
            with self.assertRaises(Exception) as raised:
                routes_vm.create_vm_draft(
                    request,
                    [VMPost(url="https://x.com/example/status/1", text="")],
                )
        self.assertEqual(raised.exception.status_code, 422)


class VMZenPromptTests(unittest.TestCase):
    @patch.object(zen_writer, "_rate_limited", return_value=False)
    @patch.object(zen_writer.urllib.request, "urlopen")
    def test_zen_generalizes_posts_to_news_prompt(self, urlopen, _rate_limited):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "choices": [{
                        "message": {
                            "content": json.dumps({
                                "prompt": "Marvel Studios Ghost Rider Ryan Gosling announcement",
                            }),
                        },
                    }],
                }).encode("utf-8")

        urlopen.return_value = FakeResponse()
        with patch.object(
            zen_writer,
            "settings",
            SimpleNamespace(
                opencode_api_key="test-key",
                opencode_fast_model="deepseek-v4-flash",
                opencode_model="deepseek-v4-flash",
            ),
        ):
            result = zen_writer.generic_news_prompt_from_x_posts_with_zen([
                {
                    "url": "https://x.com/MarvelStudios/status/1",
                    "text": "Ryan Gosling will star in Marvel Studios' Ghost Rider.",
                    "reason": "Official casting announcement",
                    "angle": "Entertainment news",
                    "source_assessment": "Primary source",
                },
            ])
        self.assertEqual(result, "Marvel Studios Ghost Rider Ryan Gosling announcement")
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        request_prompt = body["messages"][0]["content"]
        self.assertIn("reason=Official casting announcement", request_prompt)
        self.assertIn("angle=Entertainment news", request_prompt)
        self.assertIn("source_assessment=Primary source", request_prompt)
        self.assertEqual(body["model"], "deepseek-v4-flash")
        self.assertIn("opencode.ai/zen/v1/chat/completions", request.full_url)

    @patch.object(zen_writer, "_rate_limited", return_value=False)
    @patch.object(zen_writer, "_record_429")
    @patch.object(zen_writer.urllib.request, "urlopen")
    def test_zen_prompt_retries_alternate_model(self, urlopen, record_429, _rate_limited):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps({
                    "choices": [{
                        "message": {
                            "content": '{"prompt":"Federal Reserve interest rate decision"}',
                        },
                    }],
                }).encode("utf-8")

        urlopen.side_effect = [
            urllib.error.HTTPError(
                "https://opencode.ai/zen/v1/chat/completions",
                429,
                "quota",
                {},
                None,
            ),
            FakeResponse(),
        ]
        with patch.object(
            zen_writer,
            "settings",
            SimpleNamespace(
                opencode_api_key="test-key",
                opencode_fast_model="deepseek-v4-flash",
                opencode_model="deepseek-v4-flash",
            ),
        ):
            result = zen_writer.generic_news_prompt_from_x_posts_with_zen([
                {"url": "https://x.com/example/status/1", "text": "Fed decision update"},
            ])

        self.assertEqual(result, "Federal Reserve interest rate decision")
        self.assertEqual(urlopen.call_count, 2)
        record_429.assert_called_once()
        models = [json.loads(call.args[0].data)["model"] for call in urlopen.call_args_list]
        self.assertEqual(models[0], "deepseek-v4-flash")
        self.assertEqual(models[1], "minimax-m2.7")


if __name__ == "__main__":
    unittest.main()
