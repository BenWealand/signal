from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api import routes_articles
from app.api.routes_articles import XTrendArticleRequest


class AgentAccessTest(unittest.TestCase):
    def setUp(self):
        self._settings = routes_articles.settings

    def tearDown(self):
        routes_articles.settings = self._settings

    def test_agent_token_fails_closed_when_unconfigured(self):
        routes_articles.settings = SimpleNamespace(signal_api_token="", public_article_base_url="")
        with self.assertRaises(HTTPException) as ctx:
            routes_articles._require_signal_agent_token(x_signal_token="anything")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_agent_token_accepts_bearer_or_signal_header(self):
        routes_articles.settings = SimpleNamespace(signal_api_token="secret", public_article_base_url="")
        routes_articles._require_signal_agent_token(x_signal_token="secret")
        routes_articles._require_signal_agent_token(authorization="Bearer secret")
        with self.assertRaises(HTTPException) as ctx:
            routes_articles._require_signal_agent_token(authorization="Bearer wrong")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_x_payload_builds_prompt_from_topic_and_snippet(self):
        payload = XTrendArticleRequest(
            trending_topic="#BudgetVote",
            snippet="Lawmakers are posting competing claims about the overnight budget vote.",
        )
        prompt = routes_articles._prompt_from_x_payload(payload)
        self.assertIn("Trending topic: #BudgetVote", prompt)
        self.assertIn("Social post snippet:", prompt)

    def test_article_public_url_uses_configured_base(self):
        routes_articles.settings = SimpleNamespace(
            signal_api_token="secret",
            public_article_base_url="https://signal.example.com/",
        )
        self.assertEqual(
            routes_articles.article_public_url("write-123"),
            "https://signal.example.com/?article=write-123",
        )


if __name__ == "__main__":
    unittest.main()
