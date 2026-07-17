from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api import routes_admin
from app.api.routes_admin import AdminFeedShareRequest, AdminRunRequest
from app.x.models import XCandidate, XPostResult


ARTICLE = {
    "id": "write-feed-1",
    "headline": "Markets Watch the Federal Reserve",
    "dek": "Officials held rates steady after their latest meeting.",
    "body": ["Investors weighed the statement against recent inflation data."],
    "section": "markets",
    "sourceCount": 6,
    "generation_mode": "fast",
    "createdAt": "2026-07-16T12:00:00Z",
}


class XFeedSharingTests(unittest.TestCase):
    def test_feed_drafts_use_existing_article_formatter(self):
        stored = {**ARTICLE, "xShare": {"posted": False}}
        with (
            patch.object(routes_admin, "_require_admin", return_value={"id": 1}),
            patch.object(routes_admin.queries, "list_recent_x_feed_articles", return_value=[stored]),
            patch.object(routes_admin, "article_public_url", return_value="https://signal.example/article/write-feed-1"),
        ):
            result = routes_admin.admin_x_feed_drafts(authorization="Bearer admin")

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["unposted"], 1)
        draft = result["drafts"][0]
        self.assertTrue(draft["replyText"].startswith(ARTICLE["headline"]))
        self.assertTrue(draft["replyText"].endswith("/article/write-feed-1"))
        self.assertEqual(draft["section"], "markets")

    def test_live_share_is_idempotent_after_success(self):
        existing = {
            "x_post_id": "post-123",
            "x_post_url": "https://x.com/i/web/status/post-123",
        }
        with (
            patch.object(routes_admin, "_require_admin", return_value={"id": 1}),
            patch.object(routes_admin.queries, "get_generated_article", return_value=ARTICLE),
            patch.object(routes_admin.queries, "get_posted_x_share", return_value=existing),
            patch.object(routes_admin, "get_x_client") as client,
        ):
            result = routes_admin.admin_x_feed_share(
                AdminFeedShareRequest(article_id=ARTICLE["id"], dry_run=False),
                authorization="Bearer admin",
            )

        client.assert_not_called()
        self.assertEqual(result["status"], "already_posted")
        self.assertEqual(result["postId"], "post-123")

    def test_live_share_records_x_result(self):
        x_result = XPostResult(
            ok=True,
            dry_run=False,
            posted=True,
            post_id="post-456",
            post_url="https://x.com/i/web/status/post-456",
            message="Posted to X",
            provider="x-api",
        )
        client = SimpleNamespace(post_tweet=lambda text, dry_run: x_result)
        with (
            patch.object(routes_admin, "_require_admin", return_value={"id": 1}),
            patch.object(routes_admin.queries, "get_generated_article", return_value=ARTICLE),
            patch.object(routes_admin.queries, "get_posted_x_share", return_value={}),
            patch.object(routes_admin.queries, "record_x_article_share") as record,
            patch.object(routes_admin, "get_x_client", return_value=client),
            patch.object(routes_admin, "article_public_url", return_value="https://signal.example/article/write-feed-1"),
        ):
            result = routes_admin.admin_x_feed_share(
                AdminFeedShareRequest(article_id=ARTICLE["id"], dry_run=False),
                authorization="Bearer admin",
            )

        self.assertEqual(result["status"], "posted")
        self.assertEqual(result["postId"], "post-456")
        record.assert_called_once()
        self.assertEqual(record.call_args.kwargs["status"], "posted")

    def test_feed_share_replies_when_x_url_is_present(self):
        x_result = XPostResult(
            ok=True,
            dry_run=False,
            posted=True,
            post_id="reply-789",
            post_url="https://x.com/i/web/status/reply-789",
            message="Posted to X",
            provider="x-api",
        )
        client = SimpleNamespace(
            reply_to_post=lambda post_id, text, dry_run: x_result,
            post_tweet=lambda text, dry_run: self.fail("standalone post should not be used"),
        )
        reply_url = "https://x.com/example/status/123456"
        with (
            patch.object(routes_admin, "_require_admin", return_value={"id": 1}),
            patch.object(routes_admin.queries, "get_generated_article", return_value=ARTICLE),
            patch.object(routes_admin.queries, "get_posted_x_share", return_value={}),
            patch.object(routes_admin.queries, "record_x_article_share") as record,
            patch.object(routes_admin, "get_x_client", return_value=client),
            patch.object(routes_admin, "article_public_url", return_value="https://signal.example/article/write-feed-1"),
        ):
            result = routes_admin.admin_x_feed_share(
                AdminFeedShareRequest(article_id=ARTICLE["id"], dry_run=False, reply_url=reply_url),
                authorization="Bearer admin",
            )

        self.assertEqual(result["status"], "posted")
        self.assertEqual(result["replyToPostId"], "123456")
        self.assertEqual(record.call_args.kwargs["reply_to_post_id"], "123456")
        self.assertEqual(record.call_args.kwargs["reply_url"], reply_url)

    def test_promote_prompt_carries_reply_target_without_lookup(self):
        reply_url = "https://x.com/example/status/777"
        payload = AdminRunRequest(
            prompt="Federal Reserve rate decision",
            reply_url=reply_url,
            dry_run=True,
            auto_post=False,
        )
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        with (
            patch.object(routes_admin, "_require_admin", return_value={"id": 1}),
            patch.object(routes_admin, "_check_article_rate_limit"),
            patch.object(routes_admin, "run_x_pipeline", return_value={"packages": []}) as run,
            patch.object(routes_admin, "get_x_client") as client,
        ):
            routes_admin.admin_x_run(request, payload, authorization="Bearer admin")

        client.assert_not_called()
        candidate = run.call_args.kwargs["candidates"][0]
        self.assertEqual(candidate.prompt, "Federal Reserve rate decision")
        self.assertEqual(candidate.post_id, "777")
        self.assertEqual(candidate.trend_url, reply_url)
        self.assertEqual(run.call_args.kwargs["direct_prompt"], "")

    def test_promote_link_alone_uses_linked_post_as_seed(self):
        reply_url = "https://x.com/example/status/888"
        linked = XCandidate(
            topic="Senate passes overnight budget bill",
            prompt="Senate passes overnight budget bill",
            post_id="888",
            provider="x-api-lookup",
        )
        client = SimpleNamespace(lookup_post=lambda post_id: linked)
        payload = AdminRunRequest(prompt="", query="", reply_url=reply_url)
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        with (
            patch.object(routes_admin, "_require_admin", return_value={"id": 1}),
            patch.object(routes_admin, "_check_article_rate_limit"),
            patch.object(routes_admin, "run_x_pipeline", return_value={"packages": []}) as run,
            patch.object(routes_admin, "get_x_client", return_value=client),
        ):
            routes_admin.admin_x_run(request, payload, authorization="Bearer admin")

        candidate = run.call_args.kwargs["candidates"][0]
        self.assertEqual(candidate.prompt, linked.prompt)
        self.assertEqual(candidate.post_id, "888")
        self.assertEqual(candidate.trend_url, reply_url)


if __name__ == "__main__":
    unittest.main()
