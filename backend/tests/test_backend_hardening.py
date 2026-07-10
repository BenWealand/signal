from __future__ import annotations

import io
import json
import sys
import time
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.api import routes_articles, routes_users
from app.db import queries
from app.llm import gemini_writer
from app.policy import prompt_filter
from app.processing import article_writer


class _FakeCursor:
    def __init__(self):
        self.sql = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.sql = sql
        self.params = params

    def fetchone(self):
        return {
            "id": 1,
            "name": "Pat",
            "email": "pat@example.com",
            "plan": "Reader",
            "supabase_user_id": "11111111-1111-1111-1111-111111111111",
        }


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class BackendHardeningTest(unittest.TestCase):
    def test_upsert_user_persists_supabase_user_id(self):
        cursor = _FakeCursor()
        with patch.object(queries, "get_connection", return_value=_FakeConnection(cursor)):
            result = queries.upsert_user(
                "Pat",
                "pat@example.com",
                "Reader",
                "11111111-1111-1111-1111-111111111111",
            )

        self.assertIn("supabase_user_id", cursor.sql)
        self.assertEqual(cursor.params[-1], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(result["supabase_user_id"], "11111111-1111-1111-1111-111111111111")

    def test_user_routes_fail_closed_when_agent_token_is_configured(self):
        original = routes_users.settings
        routes_users.settings = SimpleNamespace(signal_api_token="expected")
        try:
            with self.assertRaises(HTTPException) as ctx:
                routes_users._require_user_route_guard(user_id=1, x_signal_token="")
            self.assertEqual(ctx.exception.status_code, 401)

            routes_users._require_user_route_guard(user_id=1, x_signal_token="expected")
        finally:
            routes_users.settings = original

    def test_social_user_id_requires_route_guard(self):
        with patch.object(routes_users, "_require_user_route_guard", return_value=42) as guard, \
             patch.object(routes_users.queries, "like_article", return_value={"liked": True}) as like_article:
            result = routes_users.like_article(
                "article-1",
                routes_users.ArticleLikePayload(user_id=7, session_id="s", actor_name="Pat"),
                x_signal_token="",
                authorization="Bearer token",
            )

        self.assertEqual(result["liked"], True)
        guard.assert_called_once_with(7, x_signal_token="", authorization="Bearer token")
        like_article.assert_called_once_with("article-1", 42, "s", "Pat")

    def test_article_request_size_and_rate_limit(self):
        with self.assertRaises(ValidationError):
            routes_articles.TrendArticleRequest(prompt="x" * (routes_articles.MAX_PROMPT_CHARS + 1))

        key = f"test:{time.monotonic()}"
        for _ in range(routes_articles.ARTICLE_RATE_LIMIT):
            routes_articles._check_article_rate_limit(key)
        with self.assertRaises(HTTPException) as ctx:
            routes_articles._check_article_rate_limit(key)
        self.assertEqual(ctx.exception.status_code, 429)

    def test_prompt_blacklist_blocks_generation_requests(self):
        original_settings = prompt_filter.settings
        prompt_filter.settings = SimpleNamespace(prompt_blacklist="forbidden topic", prompt_blacklist_regex="")
        try:
            with self.assertRaises(HTTPException) as ctx:
                routes_articles._reject_blocked_prompt("latest coverage of forbidden topic")
            self.assertEqual(ctx.exception.status_code, 422)
            self.assertEqual(ctx.exception.detail["code"], "prompt_blocked")
        finally:
            prompt_filter.settings = original_settings

    def test_prompt_blacklist_does_not_match_partial_words(self):
        original_settings = prompt_filter.settings
        prompt_filter.settings = SimpleNamespace(prompt_blacklist="war", prompt_blacklist_regex="")
        try:
            self.assertFalse(prompt_filter.prompt_is_blocked("award season coverage").blocked)
            self.assertTrue(prompt_filter.prompt_is_blocked("war coverage").blocked)
        finally:
            prompt_filter.settings = original_settings

    def test_article_progress_isolated_by_build_id(self):
        article_writer._set_progress("build-a", active=True, prompt="alpha", stage="fetching")
        article_writer._set_progress("build-b", active=True, prompt="beta", stage="writing")

        self.assertEqual(article_writer.get_build_progress("build-a")["prompt"], "alpha")
        self.assertEqual(article_writer.get_build_progress("build-b")["prompt"], "beta")
        self.assertEqual(article_writer.get_build_progress()["build_id"], "build-b")

    def test_gemini_429_fallback_is_reachable(self):
        original_settings = gemini_writer.settings
        original_last_429 = gemini_writer._last_429_at
        gemini_writer.settings = SimpleNamespace(gemini_api_key="key", gemini_model="gemini-2.0-flash")
        gemini_writer._last_429_at = 0.0
        gemini_writer._call_times.clear()

        fallback_text = "Paragraph one has enough detail to pass validation. " * 4
        calls = []

        def fake_urlopen(_req, timeout=30):
            calls.append(_req.full_url)
            if len(calls) == 1:
                body = json.dumps({"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}}).encode("utf-8")
                raise urllib.error.HTTPError(_req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))
            return _FakeResponse({"candidates": [{"content": {"parts": [{"text": fallback_text}]}}]})

        try:
            with patch.object(gemini_writer.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = gemini_writer.write_article_with_gemini(
                    "test topic",
                    [{"source_name": "Source", "title": "Title", "raw_text": "Source material. " * 80}],
                )
        finally:
            gemini_writer.settings = original_settings
            gemini_writer._last_429_at = original_last_429
            gemini_writer._call_times.clear()

        self.assertEqual(result, fallback_text.strip())
        self.assertEqual(len(calls), 2)
        self.assertIn("gemini-1.5-flash-latest", calls[1])


if __name__ == "__main__":
    unittest.main()
