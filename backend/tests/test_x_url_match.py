from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api import routes_admin
from app.api.routes_admin import AdminMatchUrlsRequest, AdminRunRequest
from app.x import match as match_mod
from app.x.models import XCandidate


class XUrlMatchTests(unittest.TestCase):
    def test_extract_x_urls_dedupes_status_links(self):
        raw = """
        https://x.com/alice/status/111
        junk
        https://twitter.com/bob/status/222?s=20
        https://x.com/alice/status/111
        33333333
        """
        urls = match_mod.extract_x_urls(raw)
        self.assertEqual(
            urls,
            [
                "https://x.com/alice/status/111",
                "https://twitter.com/bob/status/222?s=20",
                "https://x.com/i/web/status/33333333",
            ],
        )

    def test_match_urls_uses_deterministic_scoring_and_builds_reply_packages(self):
        article = {
            "id": "write-1",
            "headline": "Federal Reserve Holds Rates Steady",
            "dek": "Officials kept policy unchanged.",
            "body": ["Investors watched the statement closely."],
            "section": "markets",
            "xShare": {"posted": False},
        }
        posts_text = "https://x.com/markets/status/999"
        client = SimpleNamespace(
            lookup_post=lambda post_id: XCandidate(
                topic="Fed holds rates",
                snippet="The Federal Reserve held rates steady today.",
                prompt="Fed holds rates",
                post_id=post_id,
                author_handle="markets",
                trend_url=f"https://x.com/markets/status/{post_id}",
                provider="x-api-lookup",
            )
        )
        with (
            patch.object(match_mod, "get_x_client", return_value=client),
            patch.object(match_mod.queries, "list_recent_x_feed_articles", return_value=[article]),
            patch.object(match_mod, "article_public_url", return_value="https://signal.example/article/write-1"),
        ):
            result = match_mod.match_x_urls_to_articles(posts_text, hours=72)

        self.assertEqual(result["source"], "deterministic")
        self.assertEqual(result["matched"], 1)
        row = result["rows"][0]
        self.assertEqual(row["articleId"], "write-1")
        self.assertEqual(row["status"], "matched")
        self.assertIn("/article/write-1", row["replyText"])
        self.assertIn("in_reply_to", row["intentUrl"])

    def test_admin_match_urls_endpoint_requires_admin(self):
        payload = AdminMatchUrlsRequest(urls="https://x.com/a/status/1")
        with (
            patch.object(routes_admin, "_require_admin", return_value={"id": 1}),
            patch.object(
                routes_admin,
                "match_x_urls_to_articles",
                return_value={"count": 0, "matched": 0, "rows": [], "source": "none"},
            ) as match,
        ):
            result = routes_admin.admin_x_match_urls(payload, authorization="Bearer admin")
        match.assert_called_once()
        self.assertEqual(result["count"], 0)

    def test_admin_promote_uses_regular_article_writer(self):
        payload = AdminRunRequest(prompt="Federal Reserve rate decision", dry_run=True)
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        with (
            patch.object(routes_admin, "_require_admin", return_value={"id": 1}),
            patch.object(routes_admin, "_check_article_rate_limit"),
            patch.object(routes_admin, "run_x_pipeline", return_value={"packages": []}) as run,
        ):
            routes_admin.admin_x_run(request, payload, authorization="Bearer admin")
        self.assertIs(run.call_args.kwargs["write_fn"], routes_admin.write_article_from_prompt)


class ZenMatchParseTest(unittest.TestCase):
    @patch("app.llm.zen_writer._rate_limited", return_value=False)
    @patch("app.llm.zen_writer.settings")
    @patch("app.llm.zen_writer.urllib.request.urlopen")
    def test_match_x_posts_to_articles_with_zen(self, urlopen, settings, _rate):
        from app.llm.zen_writer import match_x_posts_to_articles_with_zen

        settings.opencode_api_key = "test-key"
        settings.opencode_fast_model = "deepseek-v4-flash"
        settings.opencode_model = "deepseek-v4-flash"

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, *_args):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        [
                                            {
                                                "postId": "1",
                                                "articleId": "a1",
                                                "confidence": 0.8,
                                                "reason": "same story",
                                            }
                                        ]
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")

        urlopen.return_value = FakeResp()
        rows = match_x_posts_to_articles_with_zen(
            [{"postId": "1", "text": "Fed holds rates", "author": "markets"}],
            [{"id": "a1", "headline": "Federal Reserve Holds Rates", "dek": "Steady policy", "section": "markets"}],
        )
        self.assertEqual(rows[0]["articleId"], "a1")
        self.assertEqual(rows[0]["confidence"], 0.8)
        request = urlopen.call_args.args[0]
        self.assertIn("opencode.ai/zen/v1/chat/completions", request.full_url)
        self.assertEqual(json.loads(request.data)["model"], "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
