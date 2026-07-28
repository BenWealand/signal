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
from app.llm import zen_writer
from app.policy import prompt_filter
from app.processing import article_writer


def _model_from_request(req) -> str:
    return json.loads(req.data.decode("utf-8"))["model"]


def _openai_package_response(text: str) -> dict:
    return {"choices": [{"message": {"content": text}}]}


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


class _FakePurgeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=()):
        self.executed.append((sql, params))
        if "DELETE FROM generated_articles" in sql:
            self.rowcount = 1

    def fetchall(self):
        return self.rows


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


_VALID_ARTICLE_PARAGRAPHS = [
    "The first paragraph contains enough sourced detail to pass article package validation cleanly.",
    "The second paragraph adds confirmed context from the supplied public source material for readers.",
]
_VALID_ARTICLE_BODY = "\n\n".join(_VALID_ARTICLE_PARAGRAPHS)
_VALID_ARTICLE_PACKAGE_TEXT = json.dumps({
    "headline": "Public Sources Confirm Major Test Development",
    "dek": "Multiple public reports provide the confirmed details used in this test article.",
    "body": _VALID_ARTICLE_PARAGRAPHS,
})


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
        self.assertIn("11111111-1111-1111-1111-111111111111", cursor.params)
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

    def test_user_routes_fail_closed_when_auth_is_not_configured(self):
        original = routes_users.settings
        routes_users.settings = SimpleNamespace(signal_api_token="", supabase_jwt_secret="")
        try:
            self.assertIsNone(routes_users._require_user_route_guard(user_id=None))
            with self.assertRaises(HTTPException) as ctx:
                routes_users._require_user_route_guard(user_id=1)
            self.assertEqual(ctx.exception.status_code, 503)
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

    def test_purge_legacy_generated_articles_removes_clear_noncompliant_rows(self):
        base_row = {
            "owner_user_id": None,
            "source": "Signal desk",
            "tag": "prompt",
            "trend_url": "",
            "dek": "",
            "summary": "",
            "facts": "[]",
            "terms": "[]",
            "sources": "[]",
            "source_links": "[]",
            "consensus": "[]",
            "source_count": 1,
            "denied_for_bias": 0,
            "fairness_score": 80,
            "accuracy_score": 80,
            "score_metadata": "{}",
            "source_quality": "{}",
            "consensus_level": "",
            "section": "",
            "status": "published",
            "created_at": "2026-07-10T00:00:00Z",
        }
        cursor = _FakePurgeCursor([
            {
                **base_row,
                "id": "legacy-1",
                "prompt": "old",
                "headline": "Old",
                "body": "[]",
                "fallback_reason": "quality_gate_failed",
                "generation_mode": "fast",
                "used_live_sources": True,
            },
            {
                **base_row,
                "id": "legacy-2",
                "prompt": "offline",
                "headline": "Offline",
                "body": '["body"]',
                "fallback_reason": "",
                "generation_mode": "offline-preview",
                "used_live_sources": False,
            },
        ])
        with patch.object(queries, "get_connection", return_value=_FakeConnection(cursor)):
            result = queries.purge_legacy_generated_articles(limit=25)

        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["articleIds"], ["legacy-1", "legacy-2"])
        deletes = [sql for sql, _params in cursor.executed if "DELETE FROM generated_articles" in sql]
        self.assertEqual(len(deletes), 2)

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

    def test_zen_429_fallback_is_reachable(self):
        original_settings = zen_writer.settings
        original_last_429 = zen_writer._last_429_at
        zen_writer.settings = SimpleNamespace(
            opencode_api_key="key",
            opencode_model="deepseek-v4-flash",
            opencode_fast_model="deepseek-v4-flash",
        )
        zen_writer._last_429_at = 0.0
        zen_writer._call_times.clear()

        fallback_text = _VALID_ARTICLE_PACKAGE_TEXT
        calls = []
        models = []

        def fake_urlopen(_req, timeout=30):
            calls.append(_req.full_url)
            models.append(_model_from_request(_req))
            if len(calls) == 1:
                body = json.dumps({"error": {"message": "quota", "type": "rate_limit_error"}}).encode("utf-8")
                raise urllib.error.HTTPError(_req.full_url, 429, "Too Many Requests", {}, io.BytesIO(body))
            return _FakeResponse(_openai_package_response(fallback_text))

        try:
            with (
                patch.object(zen_writer.urllib.request, "urlopen", side_effect=fake_urlopen),
                patch.object(zen_writer, "_sleep_before_retry", return_value=None),
            ):
                result = zen_writer.write_article_with_zen(
                    "test topic",
                    [{"source_name": "Source", "title": "Title", "raw_text": "Source material. " * 80}],
                )
        finally:
            zen_writer.settings = original_settings
            zen_writer._last_429_at = original_last_429
            zen_writer._call_times.clear()

        self.assertEqual(result, _VALID_ARTICLE_BODY)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("opencode.ai/zen/v1/chat/completions" in url for url in calls))
        self.assertEqual(models[0], "deepseek-v4-flash")
        self.assertEqual(models[1], "minimax-m2.7")

    def test_zen_503_primary_falls_back_to_failover_model(self):
        original_settings = zen_writer.settings
        original_last_error = zen_writer._last_error
        original_last_429 = zen_writer._last_429_at
        zen_writer.settings = SimpleNamespace(
            opencode_api_key="key",
            opencode_model="deepseek-v4-flash",
            opencode_fast_model="deepseek-v4-flash",
        )
        zen_writer._last_429_at = 0.0
        zen_writer._call_times.clear()

        article_text = _VALID_ARTICLE_PACKAGE_TEXT
        calls = []
        requests = []
        models = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            requests.append(req)
            models.append(_model_from_request(req))
            if len(calls) == 1:
                body = json.dumps({
                    "error": {
                        "message": "This model is currently experiencing high demand.",
                        "type": "server_error",
                    },
                }).encode("utf-8")
                raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, io.BytesIO(body))
            return _FakeResponse(_openai_package_response(article_text))

        try:
            with (
                patch.object(zen_writer.urllib.request, "urlopen", side_effect=fake_urlopen),
                patch.object(zen_writer, "_sleep_before_retry", return_value=None),
            ):
                result = zen_writer.write_article_with_zen(
                    "test topic",
                    [{"source_name": "Source", "title": "Title", "raw_text": "Source material. " * 80}],
                    mode="fast",
                )
        finally:
            zen_writer.settings = original_settings
            zen_writer._last_error = original_last_error
            zen_writer._last_429_at = original_last_429
            zen_writer._call_times.clear()

        self.assertEqual(result, _VALID_ARTICLE_BODY)
        self.assertEqual(len(calls), 2)
        self.assertEqual(models[0], "deepseek-v4-flash")
        self.assertEqual(models[1], "minimax-m2.7")
        self.assertTrue(all("opencode.ai/zen/v1/chat/completions" in url for url in calls))
        payload = json.loads(requests[0].data.decode("utf-8"))
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"][0]["role"], "user")
        self.assertEqual(requests[0].headers.get("Authorization"), "Bearer key")

    def test_zen_incomplete_primary_response_retries_alternate_model(self):
        original_settings = zen_writer.settings
        original_last_error = zen_writer._last_error
        original_last_429 = zen_writer._last_429_at
        zen_writer.settings = SimpleNamespace(
            opencode_api_key="key",
            opencode_model="deepseek-v4-flash",
            opencode_fast_model="deepseek-v4-flash",
        )
        zen_writer._last_429_at = 0.0
        zen_writer._call_times.clear()
        calls = []
        models = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            models.append(_model_from_request(req))
            text = "incomplete response" if len(calls) == 1 else _VALID_ARTICLE_PACKAGE_TEXT
            return _FakeResponse(_openai_package_response(text))

        try:
            with patch.object(zen_writer.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = zen_writer.write_article_with_zen(
                    "test topic",
                    [{"source_name": "Source", "title": "Title", "raw_text": "Source material. " * 80}],
                    mode="fast",
                )
        finally:
            zen_writer.settings = original_settings
            zen_writer._last_error = original_last_error
            zen_writer._last_429_at = original_last_429
            zen_writer._call_times.clear()

        self.assertEqual(result, _VALID_ARTICLE_BODY)
        self.assertEqual(len(calls), 2)
        self.assertEqual(models[0], "deepseek-v4-flash")
        self.assertEqual(models[1], "minimax-m2.7")

    def test_zen_exhausted_failover_reports_provider_reason(self):
        original_settings = zen_writer.settings
        original_last_error = zen_writer._last_error
        original_last_429 = zen_writer._last_429_at
        zen_writer.settings = SimpleNamespace(
            opencode_api_key="key",
            opencode_model="deepseek-v4-flash",
            opencode_fast_model="deepseek-v4-flash",
        )
        zen_writer._last_429_at = 0.0
        zen_writer._call_times.clear()
        calls = []

        def fake_urlopen(req, timeout=30):
            calls.append(req.full_url)
            body = json.dumps({
                "error": {
                    "message": "This model is currently experiencing high demand.",
                    "type": "server_error",
                },
            }).encode("utf-8")
            raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, io.BytesIO(body))

        try:
            with (
                patch.object(zen_writer.urllib.request, "urlopen", side_effect=fake_urlopen),
                patch.object(zen_writer, "_sleep_before_retry", return_value=None),
            ):
                result = zen_writer.write_article_with_zen(
                    "test topic",
                    [{"source_name": "Source", "title": "Title", "raw_text": "Source material. " * 80}],
                    mode="fast",
                )
            error = zen_writer.get_last_zen_error()
            explanation = zen_writer.describe_last_zen_error()
        finally:
            zen_writer.settings = original_settings
            zen_writer._last_error = original_last_error
            zen_writer._last_429_at = original_last_429
            zen_writer._call_times.clear()

        self.assertIsNone(result)
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(error["http_status"], 503)
        self.assertGreaterEqual(len(error["attempted_models"]), 2)
        self.assertIn("temporarily unavailable after trying", explanation)
        self.assertIn("high demand", explanation)

    def test_required_zen_article_surfaces_diagnostic_reason(self):
        reason = "OpenCode Zen is temporarily unavailable after trying 2 models (HTTP 503)."
        with (
            patch.object(zen_writer, "write_article_package_with_zen", return_value=None),
            patch.object(zen_writer, "describe_last_zen_error", return_value=reason),
        ):
            with self.assertRaises(article_writer.ZenArticleUnavailable) as ctx:
                article_writer._article_body(
                    "test topic",
                    [{"source_name": "Source", "title": "Title", "raw_text": "Source material."}],
                    [],
                    [],
                    require_zen=True,
                )

        self.assertEqual(str(ctx.exception), reason)

    def test_legacy_gemini_model_is_remapped_to_zen_primary(self):
        original_settings = zen_writer.settings
        zen_writer.settings = SimpleNamespace(
            opencode_api_key="key",
            opencode_model="gemini-2.0-flash",
            opencode_fast_model="deepseek-v4-flash",
        )
        zen_writer._last_429_at = 0.0
        zen_writer._call_times.clear()

        article_text = _VALID_ARTICLE_PACKAGE_TEXT
        models = []

        def fake_urlopen(_req, timeout=30):
            models.append(_model_from_request(_req))
            return _FakeResponse(_openai_package_response(article_text))

        try:
            with patch.object(zen_writer.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = zen_writer.write_article_with_zen(
                    "test topic",
                    [{"source_name": "Source", "title": "Title", "raw_text": "Source material. " * 80}],
                )
        finally:
            zen_writer.settings = original_settings
            zen_writer._call_times.clear()

        self.assertEqual(result, _VALID_ARTICLE_BODY)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0], "deepseek-v4-flash")
        self.assertNotIn("gemini-2.0-flash", models)

    def test_zen_404_falls_back_to_failover_model(self):
        original_settings = zen_writer.settings
        zen_writer.settings = SimpleNamespace(
            opencode_api_key="key",
            opencode_model="custom-zen-model",
            opencode_fast_model="deepseek-v4-flash",
        )
        zen_writer._last_429_at = 0.0
        zen_writer._call_times.clear()

        article_text = _VALID_ARTICLE_PACKAGE_TEXT
        calls = []
        models = []

        def fake_urlopen(_req, timeout=30):
            calls.append(_req.full_url)
            models.append(_model_from_request(_req))
            if len(calls) == 1:
                body = json.dumps({"error": {"message": "model not found", "type": "not_found_error"}}).encode("utf-8")
                raise urllib.error.HTTPError(_req.full_url, 404, "Not Found", {}, io.BytesIO(body))
            return _FakeResponse(_openai_package_response(article_text))

        try:
            with patch.object(zen_writer.urllib.request, "urlopen", side_effect=fake_urlopen):
                result = zen_writer.write_article_with_zen(
                    "test topic",
                    [{"source_name": "Source", "title": "Title", "raw_text": "Source material. " * 80}],
                )
        finally:
            zen_writer.settings = original_settings
            zen_writer._call_times.clear()

        self.assertEqual(result, _VALID_ARTICLE_BODY)
        self.assertEqual(len(calls), 2)
        self.assertEqual(models[0], "custom-zen-model")
        self.assertEqual(models[1], "minimax-m2.7")
        self.assertTrue(all("opencode.ai/zen/v1/chat/completions" in url for url in calls))


if __name__ == "__main__":
    unittest.main()
