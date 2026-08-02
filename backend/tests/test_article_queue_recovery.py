from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db import queries
from app.jobs import article_worker
from app.llm.provider import GeminiLLMClient, LLMRateLimitError
from app.processing import article_writer


class _FakeCursor:
    def __init__(self, rowcounts: list[int] | None = None, rows: list | None = None):
        self.executed: list[tuple[str, tuple | None]] = []
        self._rowcounts = list(rowcounts or [])
        self._rows = list(rows or [])
        self.rowcount = 0

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executed.append((sql, params))
        self.rowcount = self._rowcounts.pop(0) if self._rowcounts else 0

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@contextmanager
def _fake_connection(cursor: _FakeCursor):
    conn = Mock()
    conn.cursor.return_value = cursor
    yield conn


class InterruptedJobRecoveryTests(unittest.TestCase):
    def test_recovery_requeues_interrupted_jobs_and_fails_retry_exhausted_ones(self):
        cursor = _FakeCursor(rowcounts=[1, 2])
        with patch.object(queries, "get_connection", lambda: _fake_connection(cursor)):
            result = queries.recover_interrupted_article_generation_jobs("website")

        self.assertEqual(result, {"requeued": 2, "failed": 1})
        fail_sql, fail_params = cursor.executed[0]
        requeue_sql, requeue_params = cursor.executed[1]
        self.assertIn("SET status = 'failed'", fail_sql)
        self.assertIn("attempt_count >= %s", fail_sql)
        self.assertEqual(fail_params, (10, 20, "website", "website", 4))
        self.assertIn("WHEN status = 'generating' THEN 'ready_for_generation'", requeue_sql)
        self.assertIn("attempt_count = attempt_count + 1", requeue_sql)
        self.assertIn("claimed_at = NULL", requeue_sql)
        self.assertEqual(requeue_params, (10, 20, "website", "website"))

    def test_claims_stamp_a_lease_timestamp(self):
        for claim in (
            queries.claim_next_article_generation_job,
            queries.claim_ready_article_generation_job,
        ):
            cursor = _FakeCursor(rows=[None])
            with patch.object(queries, "get_connection", lambda: _fake_connection(cursor)):
                claim(lane="website")
            sql, _params = cursor.executed[0]
            self.assertIn("claimed_at = NOW()", sql)


class WorkerLoopTests(unittest.TestCase):
    @patch.object(article_worker, "_run_queue_maintenance")
    @patch.object(article_worker, "_generate_claimed_job")
    @patch.object(article_worker.queries, "claim_ready_article_generation_job")
    @patch.object(article_worker.queries, "claim_next_article_generation_job")
    @patch.object(article_worker.time, "sleep")
    def test_loop_fills_generation_slots_and_survives_claim_errors(
        self,
        sleep,
        claim_next,
        claim_ready,
        generate,
        maintenance,
    ):
        job_one = {"id": "build-1", "prompt": "a", "mode": "fast", "payload": {}}
        job_two = {"id": "build-2", "prompt": "b", "mode": "fast", "payload": {}}
        # First iteration: a transient DB error must not kill the loop.
        claim_next.side_effect = [RuntimeError("db blip"), {}, {}]
        claim_ready.side_effect = [job_one, job_two, {}, {}]
        sleep.side_effect = [None, SystemExit]

        with self.assertRaises(SystemExit):
            article_worker.run_forever(lane="website", generation_concurrency=2)

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(
            {call.args[0]["id"] for call in generate.call_args_list},
            {"build-1", "build-2"},
        )
        maintenance.assert_called_with("website")

    def test_x_lane_generation_stays_serialized(self):
        self.assertEqual(article_worker._generation_concurrency("x"), 1)
        self.assertGreaterEqual(article_worker._generation_concurrency("website"), 1)

    @patch.object(article_worker.queries, "recover_interrupted_article_generation_jobs")
    @patch.object(article_worker.queries, "expire_stale_background_article_jobs")
    def test_queue_maintenance_isolates_failures(self, expire, recover):
        expire.side_effect = RuntimeError("db down")
        recover.return_value = {"requeued": 1, "failed": 0}
        article_worker._run_queue_maintenance("website")
        recover.assert_called_once_with("website")


class GeminiRetryBudgetTests(unittest.TestCase):
    @patch("app.llm.provider.time.sleep")
    @patch("app.llm.provider.urllib.request.urlopen")
    def test_gemini_stops_retrying_when_total_budget_is_exhausted(self, urlopen, sleep):
        urlopen.side_effect = urllib.error.HTTPError(
            "https://example.test", 429, "Too Many Requests", {"Retry-After": "5"}, None
        )
        provider_settings = SimpleNamespace(
            gemini_model="gemini-flash-latest",
            gemini_retry_attempts=5,
            gemini_retry_base_seconds=2,
            gemini_retry_max_seconds=45,
            gemini_retry_total_budget_seconds=0.0,
            gemini_timeout_seconds=90,
            llm_top_p=0.9,
        )
        with patch("app.llm.provider.settings", provider_settings):
            with self.assertRaises(LLMRateLimitError):
                GeminiLLMClient(api_keys=["only-key"]).generate_json(
                    messages=[{"role": "user", "content": "test"}],
                    schema={"type": "object", "properties": {"ok": {"type": "string"}}},
                    max_tokens=32,
                    temperature=0,
                    timeout=5,
                )
        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()


class ProgressMapPruningTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(article_writer._progress_by_build)
        article_writer._progress_by_build.clear()

    def tearDown(self):
        article_writer._progress_by_build.clear()
        article_writer._progress_by_build.update(self._saved)

    def test_finished_builds_are_pruned_beyond_the_cap(self):
        total = article_writer._MAX_TRACKED_BUILDS + 25
        for index in range(total):
            article_writer._set_progress(f"build-{index}", active=False, stage="done")
        self.assertLessEqual(
            len(article_writer._progress_by_build),
            article_writer._MAX_TRACKED_BUILDS + 1,
        )
        # The most recent build must always survive pruning.
        self.assertIn(f"build-{total - 1}", article_writer._progress_by_build)


if __name__ == "__main__":
    unittest.main()
