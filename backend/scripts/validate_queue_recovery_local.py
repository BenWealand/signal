#!/usr/bin/env python3
"""One-off local validation of durable queue lease recovery against Postgres."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["DATABASE_URL"] = "postgresql://signal:signal@127.0.0.1:5432/signal_test"

from app.db import queries
from app.db.connection import close_pool, create_tables, get_connection


def set_claimed_age(job_id: str, minutes: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE article_generation_jobs SET claimed_at = NOW() - (%s * INTERVAL '1 minute') WHERE id = %s",
                (minutes, job_id),
            )


def status_of(job_id: str) -> tuple[str, int]:
    job = queries.get_article_generation_job(job_id)
    return str(job["status"]), int(job["attempt_count"])


def main() -> int:
    create_tables()

    website = queries.enqueue_article_generation_job("validate lease recovery website", mode="fast", priority=100, payload={})
    x_job = queries.enqueue_article_generation_job(
        "validate lease recovery x", mode="fast", priority=80, payload={"sourcePolicy": "x_response"},
    )
    print("enqueued:", website["id"], x_job["id"])

    claimed = queries.claim_next_article_generation_job(lane="website")
    assert claimed["id"] == website["id"], claimed
    assert claimed["claimed_at"] is not None
    print("website claim stamped lease:", claimed["claimed_at"])

    # Fresh lease must NOT be recovered.
    result = queries.recover_interrupted_article_generation_jobs("website")
    assert result == {"requeued": 0, "failed": 0}, result
    assert status_of(website["id"])[0] == "sourcing"

    # Simulate a dead worker: expired sourcing lease is requeued.
    set_claimed_age(website["id"], 15)
    result = queries.recover_interrupted_article_generation_jobs("website")
    assert result == {"requeued": 1, "failed": 0}, result
    status, attempts = status_of(website["id"])
    assert status == "queued" and attempts == 2, (status, attempts)
    print("expired sourcing lease requeued, attempts:", attempts)

    # Expired generating lease returns to ready_for_generation.
    claimed = queries.claim_next_article_generation_job(lane="website")
    queries.mark_article_generation_job_ready(claimed["id"], {})
    ready = queries.claim_ready_article_generation_job(lane="website")
    assert ready["id"] == website["id"] and ready["claimed_at"] is not None
    set_claimed_age(website["id"], 25)
    result = queries.recover_interrupted_article_generation_jobs("website")
    assert result == {"requeued": 1, "failed": 0}, result
    assert status_of(website["id"])[0] == "ready_for_generation"
    print("expired generating lease returned to ready_for_generation")

    # Retry budget: once attempts reach the cap, recovery fails the job.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE article_generation_jobs SET attempt_count = 4, status = 'generating', claimed_at = NOW() - INTERVAL '30 minute' WHERE id = %s",
                (website["id"],),
            )
    result = queries.recover_interrupted_article_generation_jobs("website")
    assert result == {"requeued": 0, "failed": 1}, result
    assert status_of(website["id"])[0] == "failed"
    print("retry-exhausted job failed cleanly")

    # Lane isolation: website recovery must not touch a stuck x-lane job.
    claimed_x = queries.claim_next_article_generation_job(lane="x")
    assert claimed_x["id"] == x_job["id"]
    set_claimed_age(x_job["id"], 60)
    result = queries.recover_interrupted_article_generation_jobs("website")
    assert result == {"requeued": 0, "failed": 0}, result
    assert status_of(x_job["id"])[0] == "sourcing"
    result = queries.recover_interrupted_article_generation_jobs("x")
    assert result == {"requeued": 1, "failed": 0}, result
    assert status_of(x_job["id"])[0] == "queued"
    print("lane isolation verified")

    close_pool()
    print("ALL QUEUE RECOVERY CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
