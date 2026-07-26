from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.llm.gemini_writer import (
    _emit_stream_progress,
    _parse_package_text,
    _response_text_from_parts,
)


class GeminiPackageParseTest(unittest.TestCase):
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

    def test_rejects_body_only_text_without_gemini_header(self):
        body_only = (
            "The first paragraph contains enough material to resemble an article but has no Gemini headline. "
            "It should not be accepted as a complete package.\n\n"
            "The second paragraph confirms that body text alone is insufficient for publication."
        )
        self.assertIsNone(_parse_package_text(body_only))

    def test_response_text_joins_all_non_thought_parts(self):
        parts = [
            {"text": "private reasoning", "thought": True},
            {"text": '{"headline":"Markets Rally",'},
            {"text": '"dek":"Investors respond","body":["One","Two"]}'},
        ]
        self.assertEqual(
            _response_text_from_parts(parts),
            '{"headline":"Markets Rally","dek":"Investors respond","body":["One","Two"]}',
        )

    @patch("app.llm.gemini_writer._rate_limited", return_value=False)
    @patch("app.llm.gemini_writer.settings")
    @patch("app.llm.gemini_writer.urllib.request.urlopen")
    def test_suggest_image_queries_prefers_people_phrases(self, urlopen, settings, _rate):
        from app.llm.gemini_writer import suggest_image_queries_with_gemini

        settings.gemini_api_key = "test-key"
        settings.gemini_fast_model = "gemini-flash-lite-latest"

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return b'{"candidates":[{"content":{"parts":[{"text":"[\\"Lamine Yamal Spain\\", \\"Argentina World Cup final\\", \\"Spain\\"]"}]}}]}'

        urlopen.return_value = FakeResp()
        queries = suggest_image_queries_with_gemini(
            headline="Spain and Argentina Prepare for World Cup Final",
            dek="Questions emerge regarding Lamine Yamal's training status.",
            body_paragraphs=["Spain faces Argentina after beating England."],
            topic="Spain Argentina World Cup final Lamine Yamal",
        )
        self.assertEqual(queries, ["Lamine Yamal Spain", "Argentina World Cup final"])
        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        prompt_text = body["contents"][0]["parts"][0]["text"]
        self.assertIn("User topic / prompt:", prompt_text)
        self.assertIn("NEVER return a broad/generic query", prompt_text)
        self.assertIn("interest rates", prompt_text)
        self.assertIn("TOP 5", prompt_text)
        self.assertIn("Rank by relevance", prompt_text)
        self.assertEqual(urlopen.call_args.kwargs.get("timeout"), 15)

if __name__ == "__main__":
    unittest.main()
