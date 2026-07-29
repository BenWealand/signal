from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.x import craft as craft_mod
from app.x.models import XCandidate


class XMultiLinkCraftTests(unittest.TestCase):
    def test_build_multi_link_prompt_includes_handles_and_focus(self):
        posts = [
            {"author": "alice", "text": "Senate votes overnight on the budget.", "postId": "1"},
            {"author": "bob", "text": "Markets watch the funding deadline.", "postId": "2"},
        ]
        prompt = craft_mod.build_multi_link_prompt(posts, focus="overnight budget vote")
        self.assertIn("@alice:", prompt)
        self.assertIn("@bob:", prompt)
        self.assertIn("Optional focus: overnight budget vote", prompt)
        self.assertIn("Do not treat the tweets themselves as cited news sources", prompt)

    def test_craft_article_from_x_urls_writes_one_article_and_per_post_rows(self):
        client = SimpleNamespace(
            lookup_post=lambda post_id: XCandidate(
                topic=f"topic-{post_id}",
                snippet=f"Snippet for {post_id}",
                prompt=f"topic-{post_id}",
                post_id=post_id,
                author_handle=f"user{post_id}",
                trend_url=f"https://x.com/user{post_id}/status/{post_id}",
                provider="x-api-lookup",
            )
        )

        def fake_write(prompt, limit, mode, build_id):
            self.assertIn("@user111:", prompt)
            self.assertIn("@user222:", prompt)
            self.assertEqual(mode, "fast")
            return {
                "id": "write-multi-1",
                "headline": "Budget Fight Intensifies",
                "dek": "Lawmakers traded claims overnight.",
                "body": ["Paragraph one.", "Paragraph two about the chamber deadline."],
                "section": "politics",
                "sourceCount": 6,
                "generation_mode": "fast",
                "scoreMetadata": {},
            }

        with (
            patch.object(craft_mod, "get_x_client", return_value=client),
            patch.object(craft_mod.queries, "save_generated_article", return_value=None) as save,
            patch.object(craft_mod, "article_public_url", return_value="https://signal.example/article/write-multi-1"),
        ):
            result = craft_mod.craft_article_from_x_urls(
                "https://x.com/a/status/111\nhttps://x.com/b/status/222",
                focus="budget vote",
                mode="fast",
                write_fn=fake_write,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["articleId"], "write-multi-1")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["ready"], 2)
        self.assertTrue(save.called)
        saved_article = save.call_args.args[0]
        self.assertEqual(saved_article["source"], "Signal desk")
        self.assertEqual(saved_article["tag"], "x-multi")
        self.assertEqual(len(saved_article["scoreMetadata"]["linkedXPosts"]), 2)

        first = result["posts"][0]
        self.assertEqual(first["articleId"], "write-multi-1")
        self.assertEqual(first["status"], "ready")
        self.assertIn("Budget Fight Intensifies", first["replyText"])
        self.assertIn("in_reply_to=111", first["intentUrl"])
        self.assertIn("in_reply_to=222", result["posts"][1]["intentUrl"])
        self.assertEqual(first["replyText"], result["posts"][1]["replyText"])

    def test_craft_rejects_empty_paste(self):
        result = craft_mod.craft_article_from_x_urls("not a link")
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["count"], 0)


if __name__ == "__main__":
    unittest.main()
