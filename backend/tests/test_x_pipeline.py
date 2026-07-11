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
from app.x.reply import article_public_url, build_prompt, x_reply_text
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
            "https://signal.example.com/?article=write-123",
        )

    def test_reply_text_includes_link(self):
        text = x_reply_text({"headline": "Budget Fight Intensifies"}, "https://signal.example.com/?article=1")
        self.assertIn("Budget Fight Intensifies", text)
        self.assertIn("https://signal.example.com/?article=1", text)


class XClientStubTests(unittest.TestCase):
    def setUp(self):
        self._client_settings = client_mod.settings
        import app.x.client as xc
        xc._client = None

    def tearDown(self):
        client_mod.settings = self._client_settings
        import app.x.client as xc
        xc._client = None

    def test_fetch_trending_requires_impl(self):
        client_mod.settings = SimpleNamespace(
            x_api_bearer_token="bearer",
            x_api_key="",
            x_api_secret="",
            x_access_token="",
            x_access_token_secret="",
            x_trends_woeid=1,
            x_dry_run=True,
            x_auto_post=False,
        )
        client = XClient()
        with self.assertRaises(XApiNotConfigured):
            client.fetch_trending()

    def test_post_tweet_dry_run(self):
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
        result = XClient().post_tweet("hello world", dry_run=True)
        self.assertTrue(result.ok)
        self.assertTrue(result.dry_run)
        self.assertFalse(result.posted)


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
            self.assertTrue(package.article_url.endswith("?article=write-1"))
            self.assertIn("Senate Budget Vote", package.reply_text)

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
            article_url="https://signal.example.com/?article=1",
            reply_text="Hello\n\nRead the sourced Signal write-up: https://signal.example.com/?article=1",
        )
        out = maybe_share_package(package, dry_run=True, auto_post=False)
        self.assertEqual(out.status, "ready_to_post")
        self.assertTrue(out.share.get("dry_run"))

if __name__ == "__main__":
    unittest.main()
