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
    @patch(
        "app.api.routes_articles.queries.enqueue_article_generation_job",
        return_value={"id": "build-test", "status": "queued"},
    )
    @patch("app.api.routes_users._require_user_route_guard", return_value=3)
    def test_articles_write_uses_verified_owner_and_queues_result(self, require_user, enqueue):
        payload = routes_articles.TrendArticleRequest(
            prompt="latest senate budget vote",
            limit=7,
            mode="fast",
            user_id=3,
        )
        result = routes_articles.write_article(fake_request(), payload, authorization="Bearer token")

        self.assertEqual(result["buildId"], "build-test")
        self.assertEqual(result["status"], "queued")
        require_user.assert_called_once_with(3, authorization="Bearer token")
        enqueue.assert_called_once()
        self.assertEqual(enqueue.call_args.args[0], "latest senate budget vote")
        self.assertEqual(enqueue.call_args.kwargs["mode"], "fast")
        self.assertEqual(enqueue.call_args.kwargs["payload"]["ownerUserId"], 3)


if __name__ == "__main__":
    unittest.main()
