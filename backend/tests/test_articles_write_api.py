from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api import routes_articles


def fake_article(prompt: str) -> dict:
    return {
        "id": "test-article-1",
        "source": "reader-prompt",
        "tag": "prompt",
        "trendUrl": "",
        "prompt": prompt,
        "headline": "Mocked article",
        "dek": "A mocked article response.",
        "summary": "Mocked summary",
        "body": ["Mock paragraph."],
        "facts": [],
        "terms": ["mock"],
        "sources": ["Mock Source"],
        "sourceLinks": [],
        "consensus": [],
        "sourceCount": 1,
        "deniedForBias": 0,
        "fairnessScore": 90,
        "accuracyScore": 90,
    }


def fake_request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/articles/write",
        "headers": [],
        "client": ("testclient", 50000),
    })


class ArticlesWriteApiTest(unittest.TestCase):
    @patch("app.api.routes_articles.queries.save_generated_article", return_value="test-article-1")
    @patch("app.api.routes_users._require_user_route_guard", return_value=3)
    @patch("app.api.routes_articles.write_article_from_prompt")
    def test_articles_write_uses_verified_owner_and_saves_result(self, write_article, require_user, save_article):
        write_article.side_effect = lambda prompt, **_kwargs: fake_article(prompt)

        payload = routes_articles.TrendArticleRequest(
            prompt="latest senate budget vote",
            limit=7,
            mode="fast",
            user_id=3,
        )
        result = routes_articles.write_article(fake_request(), payload, authorization="Bearer token")

        self.assertEqual(result["prompt"], "latest senate budget vote")
        self.assertEqual(result["ownerUserId"], 3)
        self.assertIn("buildId", result)
        write_article.assert_called_once()
        self.assertEqual(write_article.call_args.kwargs["limit"], 7)
        self.assertEqual(write_article.call_args.kwargs["mode"], "fast")
        require_user.assert_called_once_with(3, authorization="Bearer token")
        save_article.assert_called_once()


if __name__ == "__main__":
    unittest.main()
