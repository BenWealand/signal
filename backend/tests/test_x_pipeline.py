from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.x.client import XApiNotConfigured, XClient
from app.x.filter import filter_candidates, is_actionable_candidate
from app.x.models import XCandidate
from app.x.pipeline import maybe_share_package, run_x_pipeline, write_article_for_candidate
from app.processing.article_writer import GeminiArticleUnavailable
from app.x.reply import article_public_url, build_prompt, share_intent_url, x_reply_text
from app.x import reply as reply_mod
from app.x import client as client_mod
from app.x import pipeline as pipeline_mod


class XFilterTests(unittest.TestCase):
    def test_rejects_vague_reactions(self):
        ok, reason = is_actionable_candidate(XCandidate(topic="this is wild"))
        self.assertFalse(ok)
        self.assertEqual(reason, "vague_reaction")

    def test_accepts_newsy_topic(self):
        ok, reason = is_actionable_candidate(
            XCandidate(topic="#BudgetVote", snippet="Senate overnight budget vote dispute")
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "ok")

    def test_filter_dedupes_and_limits(self):
        rows = [
            XCandidate(topic="#BudgetVote", snippet="Senate budget vote"),
            XCandidate(topic="#BudgetVote", snippet="Senate budget vote"),
            XCandidate(topic="lol"),
            XCandidate(topic="Federal Reserve rate decision markets react"),
        ]
        kept = filter_candidates(rows, limit=2)
        self.assertEqual(len(kept), 2)
        self.assertEqual(kept[0].topic, "#BudgetVote")


class XReplyTests(unittest.TestCase):
    def setUp(self):
        self._reply_settings = reply_mod.settings

    def tearDown(self):
        reply_mod.settings = self._reply_settings

    def test_build_prompt_requires_signal(self):
        with self.assertRaises(ValueError):
            build_prompt("", "", "")

    def test_build_prompt_merges_fields(self):
        prompt = build_prompt("#BudgetVote", "Lawmakers argue overnight.", "")
        self.assertIn("Trending topic: #BudgetVote", prompt)
        self.assertIn("Social post snippet:", prompt)

    def test_article_public_url(self):
        reply_mod.settings = SimpleNamespace(public_article_base_url="https://signal.example.com/")
        self.assertEqual(
            article_public_url("write-123"),
            "https://signal.example.com/article/write-123",
        )

    def test_reply_text_includes_link(self):
        text = x_reply_text(
            {
                "headline": "Budget Fight Intensifies",
                "dek": "Lawmakers traded competing claims overnight.",
                "body": [
                    "The chamber neared a funding deadline as both parties dug in.",
                    "Republicans argued the package protects defense spending while Democrats pressed for domestic priorities.",
                ],
            },
            "https://signal.example.com/article/1",
        )
        self.assertIn("Budget Fight Intensifies", text)
        self.assertIn("Lawmakers traded competing claims overnight.", text)
        self.assertIn("…", text)
        self.assertIn("https://signal.example.com/article/1", text)
        self.assertTrue(text.endswith("https://signal.example.com/article/1"))
        # First two lines full; third truncated before the URL block.
        lines = text.split("\n")
        self.assertEqual(lines[0], "Budget Fight Intensifies")
        self.assertEqual(lines[1], "Lawmakers traded competing claims overnight.")
        self.assertTrue(lines[2].endswith("…"))
        self.assertLess(len(lines[2]), len(
            "The chamber neared a funding deadline as both parties dug in."
        ))

    def test_reply_text_uses_body_when_no_dek(self):
        text = x_reply_text(
            {
                "headline": "Markets Watch the Fed",
                "body": [
                    "Investors priced in a cautious hold ahead of the decision.",
                    "Bond yields slipped as traders dialed back rate-cut bets for the quarter.",
                ],
            },
            "https://signal.example.com/article/write-9",
        )
        self.assertIn("Investors priced in a cautious hold", text)
        self.assertIn("…", text)
        self.assertIn("/article/write-9", text)

    def test_share_intent_targets_reply_post(self):
        intent = share_intent_url(
            "https://signal.example.com/article/write-9",
            reply_text="Draft with article link",
            in_reply_to_id="123456",
        )
        self.assertIn("in_reply_to=123456", intent)
        self.assertIn("text=Draft%20with%20article%20link", intent)


class XClientTests(unittest.TestCase):
    def setUp(self):
        self._client_settings = client_mod.settings
        client_mod.reset_x_client()

    def tearDown(self):
        client_mod.settings = self._client_settings
        client_mod.reset_x_client()

    def _configured(self, **overrides):
        base = dict(
            x_api_bearer_token="bearer-token",
            x_api_key="api-key",
            x_api_secret="api-secret",
            x_access_token="access-token",
            x_access_token_secret="access-secret",
            x_trends_woeid=1,
            x_dry_run=True,
            x_auto_post=False,
        )
        base.update(overrides)
        client_mod.settings = SimpleNamespace(**base)
        return XClient()

    def test_fetch_trending_disabled(self):
        client = self._configured()
        with self.assertRaises(XApiNotConfigured):
            client.fetch_trending()

    def test_post_tweet_dry_run(self):
        result = self._configured().post_tweet("hello world", dry_run=True)
        self.assertTrue(result.ok)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.posted)
        self.assertEqual(result.provider, "x-api")

    def test_search_recent_maps_payload(self):
        client = self._configured()
        fake = {
            "data": [
                {
                    "id": "111",
                    "text": "Senate overnight budget vote dispute continues",
                    "author_id": "9",
                    "public_metrics": {"like_count": 12, "repost_count": 3, "reply_count": 1},
                }
            ],
            "includes": {"users": [{"id": "9", "username": "wiredesk"}]},
        }
        with patch.object(client, "_request", return_value=fake) as req:
            rows = client.search_recent("budget vote", limit=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].post_id, "111")
        self.assertEqual(rows[0].author_handle, "wiredesk")
        self.assertIn("status/111", rows[0].trend_url)
        self.assertEqual(req.call_args.kwargs["auth"], "bearer")

    def test_post_tweet_live(self):
        client = self._configured(x_dry_run=False)
        with patch.object(client, "_request", return_value={"data": {"id": "222", "text": "hi"}}) as req:
            result = client.post_tweet("Hello from Signal", dry_run=False)
        self.assertTrue(result.ok)
        self.assertTrue(result.posted)
        self.assertEqual(result.post_id, "222")
        self.assertEqual(req.call_args.args[0], "POST")
        self.assertEqual(req.call_args.kwargs["auth"], "oauth1")

    def test_status_id_from_url(self):
        self.assertEqual(client_mod._status_id_from_url("https://x.com/foo/status/12345"), "12345")
        self.assertEqual(client_mod._status_id_from_url("https://twitter.com/i/web/status/99"), "99")
        self.assertEqual(client_mod._status_id_from_url("https://example.com/x"), "")

    def test_oauth_header_present(self):
        header = client_mod._oauth1_header(
            "POST",
            "https://api.x.com/2/tweets",
            consumer_key="ck",
            consumer_secret="cs",
            access_token="at",
            access_token_secret="ats",
        )
        self.assertTrue(header.startswith("OAuth "))
        self.assertIn("oauth_signature=", header)


class XPipelineTests(unittest.TestCase):
    def setUp(self):
        self._pipeline_settings = pipeline_mod.settings
        self._reply_settings = reply_mod.settings
        self._client_settings = client_mod.settings
        import app.x.client as xc
        xc._client = None

    def tearDown(self):
        pipeline_mod.settings = self._pipeline_settings
        reply_mod.settings = self._reply_settings
        client_mod.settings = self._client_settings
        import app.x.client as xc
        xc._client = None

    def test_write_article_for_candidate_ready(self):
        candidate = XCandidate(
            topic="Senate budget vote overnight",
            snippet="Lawmakers clash on spending.",
            trend_url="https://x.com/example/status/1",
            post_id="1",
        )

        def fake_write(prompt, limit, mode, build_id):
            return {
                "id": "write-1",
                "headline": "Senate Budget Vote Draws Scrutiny",
                "body": ["Paragraph one.", "Paragraph two."],
                "sourceCount": 4,
                "summary": "Summary",
            }

        with patch.object(pipeline_mod.queries, "save_generated_article", return_value=None):
            pipeline_mod.settings = SimpleNamespace(
                public_article_base_url="https://signal.example.com",
                x_dry_run=True,
                x_auto_post=False,
            )
            reply_mod.settings = pipeline_mod.settings
            package = write_article_for_candidate(candidate, write_fn=fake_write)
            self.assertEqual(package.status, "ready_to_post")
            self.assertTrue(package.article_url.endswith("/article/write-1"))
            self.assertIn("Senate Budget Vote", package.reply_text)
            self.assertEqual(package.article.get("source"), "Signal desk")
            self.assertNotEqual(package.article.get("source"), "x-agent")

    def test_run_pipeline_with_manual_candidates(self):
        candidate = XCandidate(topic="Climate insurance coastal markets pressure")

        def fake_write(prompt, limit, mode, build_id):
            return {
                "id": "write-2",
                "headline": "Coastal Insurance Pressure Rises",
                "body": ["A", "B"],
                "sourceCount": 3,
                "summary": "Summary",
            }

        with patch.object(pipeline_mod.queries, "save_generated_article", return_value=None):
            pipeline_mod.settings = SimpleNamespace(
                public_article_base_url="https://signal.example.com",
                x_dry_run=True,
                x_auto_post=False,
            )
            reply_mod.settings = pipeline_mod.settings
            client_mod.settings = SimpleNamespace(
                x_api_bearer_token="",
                x_api_key="",
                x_api_secret="",
                x_access_token="",
                x_access_token_secret="",
                x_trends_woeid=1,
                x_dry_run=True,
                x_auto_post=False,
            )

            result = run_x_pipeline(
                max_articles=1,
                candidates=[candidate],
                write_fn=fake_write,
                dry_run=True,
                auto_post=False,
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["written"], 1)
            self.assertEqual(result["packages"][0]["status"], "ready_to_post")

    def test_run_pipeline_keeps_trying_after_unavailable_candidate(self):
        candidates = [
            XCandidate(topic="Weak Topic", prompt="weak topic"),
            XCandidate(topic="Climate insurance coastal markets pressure", prompt="Climate insurance coastal markets pressure"),
        ]
        calls = []

        def fake_write(prompt, limit, mode, build_id):
            calls.append(prompt)
            if len(calls) == 1:
                raise GeminiArticleUnavailable("No accessible sources were found for a Gemini draft")
            return {
                "id": "write-3",
                "headline": "Coastal Insurance Pressure Rises",
                "body": ["A", "B"],
                "sourceCount": 3,
                "summary": "Summary",
            }

        with patch.object(pipeline_mod.queries, "save_generated_article", return_value=None):
            pipeline_mod.settings = SimpleNamespace(
                public_article_base_url="https://signal.example.com",
                x_dry_run=True,
                x_auto_post=False,
            )
            reply_mod.settings = pipeline_mod.settings
            client_mod.settings = SimpleNamespace(
                x_api_bearer_token="",
                x_api_key="",
                x_api_secret="",
                x_access_token="",
                x_access_token_secret="",
                x_trends_woeid=1,
                x_dry_run=True,
                x_auto_post=False,
            )

            result = run_x_pipeline(
                max_articles=1,
                discover_limit=8,
                candidates=candidates,
                write_fn=fake_write,
                dry_run=True,
                auto_post=False,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["written"], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["packages"][0]["status"], "error")
        self.assertEqual(result["packages"][1]["status"], "ready_to_post")

    def test_run_pipeline_uses_direct_prompt_without_discovery(self):
        prompts = []

        def fake_write(prompt, limit, mode, build_id):
            prompts.append(prompt)
            return {
                "id": "write-direct",
                "headline": "Federal Reserve Policy Update",
                "body": ["A", "B"],
                "sourceCount": 3,
                "summary": "Summary",
            }

        with (
            patch.object(pipeline_mod, "discover_candidates") as discover,
            patch.object(pipeline_mod.queries, "save_generated_article", return_value=None),
        ):
            pipeline_mod.settings = SimpleNamespace(
                public_article_base_url="https://signal.example.com",
                x_dry_run=True,
                x_auto_post=False,
            )
            reply_mod.settings = pipeline_mod.settings
            client_mod.settings = SimpleNamespace(
                x_api_bearer_token="",
                x_api_key="",
                x_api_secret="",
                x_access_token="",
                x_access_token_secret="",
                x_trends_woeid=1,
                x_dry_run=True,
                x_auto_post=False,
            )

            result = run_x_pipeline(
                max_articles=1,
                direct_prompt="federal reserve",
                write_fn=fake_write,
                dry_run=True,
                auto_post=False,
            )

        discover.assert_not_called()
        self.assertEqual(result["provider"], "manual-prompt")
        self.assertEqual(result["written"], 1)
        self.assertEqual(prompts, ["federal reserve"])

    def test_manual_prompt_candidate_bypasses_trend_filter(self):
        prompts = []

        def fake_write(prompt, limit, mode, build_id):
            prompts.append(prompt)
            return {
                "id": "write-reply",
                "headline": "Fed Update",
                "body": ["A", "B"],
                "sourceCount": 3,
                "summary": "Summary",
            }

        candidate = XCandidate(
            topic="Fed",
            prompt="Fed",
            post_id="123",
            trend_url="https://x.com/example/status/123",
            provider="manual-prompt",
        )
        with patch.object(pipeline_mod.queries, "save_generated_article", return_value=None):
            pipeline_mod.settings = SimpleNamespace(
                public_article_base_url="https://signal.example.com",
                x_dry_run=True,
                x_auto_post=False,
            )
            reply_mod.settings = pipeline_mod.settings
            result = run_x_pipeline(
                max_articles=1,
                candidates=[candidate],
                write_fn=fake_write,
                dry_run=True,
                auto_post=False,
            )

        self.assertEqual(result["provider"], "manual-prompt")
        self.assertEqual(result["written"], 1)
        self.assertEqual(prompts, ["Fed"])

    def test_write_article_for_candidate_keeps_specific_prompt_clean(self):
        candidate = XCandidate(
            topic="#BudgetVote",
            prompt="latest senate budget vote",
            snippet="Lawmakers are posting competing claims about the overnight budget vote.",
        )
        prompts = []

        def fake_write(prompt, limit, mode, build_id):
            prompts.append(prompt)
            return {
                "id": "write-4",
                "headline": "Senate Budget Vote Draws Scrutiny",
                "body": ["A", "B"],
                "sourceCount": 3,
                "summary": "Summary",
            }

        with patch.object(pipeline_mod.queries, "save_generated_article", return_value=None):
            pipeline_mod.settings = SimpleNamespace(
                public_article_base_url="https://signal.example.com",
                x_dry_run=True,
                x_auto_post=False,
            )
            reply_mod.settings = pipeline_mod.settings
            package = write_article_for_candidate(candidate, write_fn=fake_write)

        self.assertEqual(package.status, "ready_to_post")
        self.assertEqual(prompts, ["latest senate budget vote"])

    def test_maybe_share_dry_run(self):
        from app.x.models import XSharePackage

        client_mod.settings = SimpleNamespace(
            x_api_bearer_token="",
            x_api_key="",
            x_api_secret="",
            x_access_token="",
            x_access_token_secret="",
            x_trends_woeid=1,
            x_dry_run=True,
            x_auto_post=False,
        )
        pipeline_mod.settings = client_mod.settings

        package = XSharePackage(
            status="ready_to_post",
            article_url="https://signal.example.com/article/1",
            reply_text="Hello\n\nRead the sourced Signal write-up: https://signal.example.com/article/1",
        )
        out = maybe_share_package(package, dry_run=True, auto_post=False)
        self.assertEqual(out.status, "ready_to_post")
        self.assertTrue(out.share.get("dry_run"))

if __name__ == "__main__":
    unittest.main()
