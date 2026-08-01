from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import main


class EmbeddedWebsiteWorkerTest(unittest.TestCase):
    def tearDown(self):
        main._website_worker_thread = None

    @patch("app.jobs.article_worker.run_forever")
    @patch("app.main.threading.Thread")
    def test_starts_one_daemon_website_lane_worker(self, thread_cls, run_forever):
        thread = Mock()
        thread.is_alive.return_value = True
        thread_cls.return_value = thread

        first = main._start_embedded_website_worker()
        second = main._start_embedded_website_worker()

        self.assertIs(first, thread)
        self.assertIs(second, thread)
        thread_cls.assert_called_once_with(
            target=run_forever,
            kwargs={"lane": "website", "poll_seconds": 1.0},
            daemon=True,
            name="render-website-article-worker",
        )
        thread.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
