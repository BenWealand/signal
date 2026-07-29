from __future__ import annotations

import json
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.llm.zen_writer import (
    _call_provider_chat,
    _emit_stream_progress,
    _gemini_message_content,
    _http_error_details,
    _message_content,
    _parse_package_text,
    write_article_package_with_zen,
)


class ZenPackageParseTest(unittest.TestCase):
    def test_http_error_details_preserve_plain_text_provider_reason(self):
        error = urllib.error.HTTPError(
            "https://opencode.ai/zen/v1/chat/completions",
            403,
            "Forbidden",
            {},
            io.BytesIO(b"Free model access limit reached"),
        )
        details = _http_error_details(error, "deepseek-v4-flash-free")
        self.assertEqual(details["http_status"], 403)
        self.assertEqual(details["message"], "Free model access limit reached")

    def test_settings_keep_zen_and_gemini_credentials_separate(self):
        settings = Settings(
            opencode_api_key="zen-key",
            gemini_api_key="gemini-key",
            opencode_model="deepseek-v4-flash",
            gemini_model="gemini-flash-latest",
        )
        self.assertEqual(settings.opencode_api_key, "zen-key")
        self.assertEqual(settings.gemini_api_key, "gemini-key")
        self.assertEqual(settings.opencode_model, "deepseek-v4-flash")
        self.assertEqual(settings.gemini_model, "gemini-flash-latest")

    def test_parses_tagged_package(self):
        text = """<<<HEADLINE>>>
Senate Passes Budget Bill Overnight
<<<DEK>>>
Lawmakers approved the package after a late floor fight.
<<<BODY>>>
First paragraph with enough detail for validation across the overnight senate vote.

Second paragraph confirming the sourced outcome from multiple public outlets covering the bill.
"""
        package = _parse_package_text(text)
        self.assertEqual(package["headline"], "Senate Passes Budget Bill Overnight")
        self.assertIn("Lawmakers approved", package["dek"])
        self.assertIn("First paragraph", package["body"])

    def test_stream_progress_exposes_partial_headline_before_body_is_long(self):
        chunks: list[dict] = []
        partial = (
            "<<<HEADLINE>>>\n"
            "Senate Passes Budget Bill Overnight\n"
            "<<<DEK>>>\n"
            "Lawmakers approved the package after a late floor fight.\n"
            "<<<BODY>>>\n"
            "Short lead."
        )
        _emit_stream_progress(partial, chunks.append)
        self.assertEqual(chunks[-1]["headline"], "Senate Passes Budget Bill Overnight")
        self.assertIn("Lawmakers approved", chunks[-1]["dek"])
        self.assertIn("Short lead", chunks[-1]["draft_text"])

    def test_parses_json_package(self):
        text = """{
  "headline": "Markets Rally After Rate Decision",
  "dek": "Investors digested the central bank statement within minutes.",
  "body": "First paragraph about the rally and what traders watched in the statement.\\n\\nSecond paragraph about yields, futures, and the immediate market reaction."
}"""
        package = _parse_package_text(text)
        self.assertEqual(package["headline"], "Markets Rally After Rate Decision")
        self.assertIn("Investors digested", package["dek"])
        self.assertIn("First paragraph", package["body"])

    def test_parses_schema_json_with_body_paragraph_array(self):
        text = json.dumps({
            "headline": "Markets Rally After Central Bank Decision",
            "dek": "Investors assessed the decision and its immediate effects across major markets.",
            "body": [
                "Stocks rose after the central bank published its latest decision, according to the supplied market reports.",
                "Bond yields and currency markets also moved as investors reviewed the statement and its policy implications.",
            ],
        })
        package = _parse_package_text(text)
        self.assertEqual(package["headline"], "Markets Rally After Central Bank Decision")
        self.assertEqual(len(package["body"].split("\n\n")), 2)

    def test_rejects_body_only_text_without_package_header(self):
        body_only = (
            "The first paragraph contains enough material to resemble an article but has no Zen headline. "
            "It should not be accepted as a complete package.\n\n"
            "The second paragraph confirms that body text alone is insufficient for publication."
        )
        self.assertIsNone(_parse_package_text(body_only))

    def test_message_content_reads_openai_chat_completion(self):
        data = {
            "choices": [{
                "message": {
                    "content": '{"headline":"Markets Rally","dek":"Investors respond","body":["One","Two"]}',
                },
            }],
        }
        self.assertEqual(
            _message_content(data),
            '{"headline":"Markets Rally","dek":"Investors respond","body":["One","Two"]}',
        )

    def test_message_content_joins_list_content_parts(self):
        data = {
            "choices": [{
                "message": {
                    "content": [
                        {"text": '{"headline":"Markets Rally",'},
                        {"text": '"dek":"Investors respond","body":["One","Two"]}'},
                    ],
                },
            }],
        }
        self.assertEqual(
            _message_content(data),
            '{"headline":"Markets Rally","dek":"Investors respond","body":["One","Two"]}',
        )

    def test_gemini_message_content_joins_candidate_parts(self):
        data = {
            "candidates": [{
                "content": {
                    "parts": [
                        {"text": '{"prompt":"central bank '},
                        {"text": 'rate decision"}'},
                    ],
                },
            }],
        }
        self.assertEqual(
            _gemini_message_content(data),
            '{"prompt":"central bank rate decision"}',
        )

    def test_provider_chain_uses_gemini_only_after_zen_failure(self):
        settings = SimpleNamespace(
            gemini_api_key="gemini-key",
            gemini_model="gemini-flash-latest",
            gemini_fast_model="gemini-flash-latest",
        )
        calls = []

        class FakeResp:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return json.dumps(self.body).encode("utf-8")

        def fake_urlopen(request, timeout=30):
            calls.append(request)
            if len(calls) == 1:
                body = json.dumps({"error": {"message": "Zen unavailable"}}).encode("utf-8")
                raise urllib.error.HTTPError(
                    request.full_url,
                    503,
                    "Service Unavailable",
                    {},
                    io.BytesIO(body),
                )
            return FakeResp({
                "candidates": [{
                    "content": {"parts": [{"text": '{"prompt":"fallback worked"}'}]},
                }],
            })

        with (
            patch("app.llm.zen_writer.settings", settings),
            patch("app.llm.zen_writer.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            result = _call_provider_chat(
                model="deepseek-v4-flash",
                prompt="Choose a prompt",
                key="zen-key",
                max_tokens=100,
                fallback_mode="fast",
            )

        self.assertEqual(result, '{"prompt":"fallback worked"}')
        self.assertEqual(len(calls), 2)
        self.assertIn("opencode.ai/zen/v1/chat/completions", calls[0].full_url)
        self.assertIn(
            "generativelanguage.googleapis.com/v1beta/models/"
            "gemini-flash-latest:generateContent",
            calls[1].full_url,
        )
        self.assertEqual(calls[0].headers["Authorization"], "Bearer zen-key")
        self.assertEqual(calls[1].headers["X-goog-api-key"], "gemini-key")

    def test_article_chain_attempts_gemini_only_once_after_all_zen_models_fail(self):
        settings = SimpleNamespace(
            opencode_api_key="zen-key",
            opencode_model="deepseek-v4-flash-free",
            opencode_fast_model="deepseek-v4-flash-free",
            gemini_api_key="gemini-key",
            gemini_model="gemini-2.5-flash-lite",
            gemini_fast_model="gemini-2.5-flash-lite",
        )
        urls: list[str] = []

        def fake_urlopen(request, timeout=30):
            urls.append(request.full_url)
            if "generativelanguage.googleapis.com" in request.full_url:
                body = json.dumps({"error": {"message": "Gemini quota exceeded", "code": 429}}).encode("utf-8")
                raise urllib.error.HTTPError(request.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))
            body = json.dumps({"error": {"message": "Zen denied", "type": "permission_error"}}).encode("utf-8")
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(body))

        with (
            patch("app.llm.zen_writer.settings", settings),
            patch("app.llm.zen_writer._rate_limited", return_value=False),
            patch("app.llm.zen_writer._sleep_before_retry", return_value=None),
            patch("app.llm.zen_writer.urllib.request.urlopen", side_effect=fake_urlopen),
        ):
            result = write_article_package_with_zen(
                "senate budget vote",
                [{
                    "source_name": "AP",
                    "title": "Senate votes on budget package",
                    "raw_text": "Lawmakers voted on the budget package after debate. " * 20,
                }],
                mode="fast",
            )

        self.assertIsNone(result)
        gemini_urls = [url for url in urls if "generativelanguage.googleapis.com" in url]
        zen_urls = [url for url in urls if "opencode.ai/zen" in url]
        self.assertGreaterEqual(len(zen_urls), 1)
        self.assertEqual(len(gemini_urls), 1)

    @patch("app.llm.zen_writer._rate_limited", return_value=False)
    @patch("app.llm.zen_writer.settings")
    @patch("app.llm.zen_writer.urllib.request.urlopen")
    def test_suggest_image_queries_prefers_people_phrases(self, urlopen, settings, _rate):
        from app.llm.zen_writer import suggest_image_queries_with_zen

        settings.opencode_api_key = "test-key"
        settings.opencode_fast_model = "deepseek-v4-flash"
        settings.opencode_model = "deepseek-v4-flash"

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return json.dumps({
                    "choices": [{
                        "message": {
                            "content": '["Lamine Yamal Spain", "Argentina World Cup final", "Spain"]',
                        },
                    }],
                }).encode("utf-8")

        urlopen.return_value = FakeResp()
        queries = suggest_image_queries_with_zen(
            headline="Spain and Argentina Prepare for World Cup Final",
            dek="Questions emerge regarding Lamine Yamal's training status.",
            body_paragraphs=["Spain faces Argentina after beating England."],
            topic="Spain Argentina World Cup final Lamine Yamal",
        )
        self.assertEqual(queries, ["Lamine Yamal Spain", "Argentina World Cup final"])
        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        prompt_text = body["messages"][0]["content"]
        self.assertIn("User topic / prompt:", prompt_text)
        self.assertIn("NEVER return a broad/generic query", prompt_text)
        self.assertIn("interest rates", prompt_text)
        self.assertIn("TOP 5", prompt_text)
        self.assertIn("Rank by relevance", prompt_text)
        self.assertEqual(body["model"], "deepseek-v4-flash")
        self.assertEqual(urlopen.call_args.kwargs.get("timeout"), 15)
        self.assertIn("opencode.ai/zen/v1/chat/completions", request.full_url)


if __name__ == "__main__":
    unittest.main()
