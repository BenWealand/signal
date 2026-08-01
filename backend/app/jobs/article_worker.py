from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import settings
from app.db import queries
from app.ingest.openverse_images import ArticleImagePicker
from app.processing.article_writer import (
    prepare_article_request,
    set_build_progress,
    write_article_from_prompt,
)

logger = logging.getLogger(__name__)
_image_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="article-image-attach")


def _payload(job: dict[str, Any]) -> dict[str, Any]:
    value = job.get("payload") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = {}
    return value if isinstance(value, dict) else {}


def _x_origin_source(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("sourcePolicy") != "x_response":
        return []
    item = payload.get("xSource") or {}
    if not isinstance(item, dict):
        return []
    url = str(item.get("url") or payload.get("trendUrl") or "").strip()
    text = str(item.get("text") or "").strip()
    if not url or not text:
        return []
    handle = str(item.get("authorHandle") or "").strip().lstrip("@")
    return [{
        "source_kind": "x-post",
        "source_name": f"@{handle} on X" if handle else "Originating post on X",
        "title": text[:180],
        "url": url,
        "raw_text": text,
        "clean_text": text,
        "description": text,
    }]


def _attach_image(article: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    if not settings.article_images_enabled:
        return {}
    picker = ArticleImagePicker(
        enabled=True,
        search_timeout=settings.article_image_search_timeout_seconds,
    )
    try:
        picker.prime_from_prompt(
            str(article.get("headline") or article.get("prompt") or ""),
            source_hints=[
                str(item.get("title") or "")
                for item in article.get("sourceLinks") or []
                if isinstance(item, dict)
            ],
        )
        image = picker.finalize(
            headline=str(article.get("headline") or ""),
            dek=str(article.get("dek") or ""),
            body=article.get("body") or [],
            wait_seconds=settings.article_image_wait_seconds,
        )
        if image:
            article["image"] = image
            if persist:
                queries.save_generated_article(article)
        else:
            logger.warning("No suitable article image found", extra={"article_id": article.get("id")})
        return image
    except Exception:
        logger.exception("Article image attachment failed", extra={"article_id": article.get("id")})
        return {}
    finally:
        picker.shutdown()


def _fail_job(job_id: str, exc: BaseException) -> None:
    logger.exception("Article generation job failed", extra={"build_id": job_id})
    message = str(exc) or "Article generation failed"
    queries.update_article_generation_job(job_id, status="failed", error=message)
    set_build_progress(
        job_id,
        active=False,
        stage="error",
        stage_label="Write failed",
        article=None,
        error=message,
    )


def _prepare_claimed_job(job: dict[str, Any]) -> bool:
    job_id = str(job["id"])
    payload = _payload(job)
    try:
        variant, sources, fingerprint, existing = prepare_article_request(
            str(job["prompt"]),
            limit=int(payload.get("limit") or 12),
            mode=str(job.get("mode") or "fast"),
            build_id=job_id,
            supplemental_sources=_x_origin_source(payload),
            source_policy=str(payload.get("sourcePolicy") or "standard"),
        )
        if existing:
            existing["buildId"] = job_id
            queries.update_article_generation_job(
                job_id,
                status="saved",
                article_id=str(existing["id"]),
            )
            set_build_progress(
                job_id,
                active=False,
                stage="done",
                stage_label="Reused recent article",
                article=existing,
                error=None,
            )
            return True
        payload["_prepared"] = {
            "variant": variant,
            "sources": sources,
            "fingerprint": fingerprint,
        }
        queries.mark_article_generation_job_ready(job_id, payload)
        is_x_article = payload.get("sourcePolicy") == "x_response"
        set_build_progress(
            job_id,
            active=True,
            stage="writing",
            stage_label=(
                "Waiting for the local X writer..."
                if is_x_article
                else "Waiting for Gemini..."
            ),
            sources_found=len(sources),
            sources_enriched=sum(
                1
                for item in sources
                if len(str(item.get("clean_text") or item.get("raw_text") or "")) >= 180
            ),
            error=None,
        )
        return True
    except Exception as exc:
        _fail_job(job_id, exc)
        return True


def _generate_claimed_job(job: dict[str, Any]) -> bool:
    job_id = str(job["id"])
    payload = _payload(job)
    prepared = payload.get("_prepared") or {}
    try:
        article = write_article_from_prompt(
            str(job["prompt"]),
            limit=int(payload.get("limit") or 12),
            mode=str(job.get("mode") or "fast"),
            build_id=job_id,
            prepared_variant=str(prepared["variant"]),
            prepared_sources=list(prepared["sources"]),
            prepared_fingerprint=str(prepared["fingerprint"]),
            source_policy=str(payload.get("sourcePolicy") or "standard"),
        )
        article["buildId"] = job_id
        article["source"] = str(payload.get("source") or article.get("source") or "Signal desk")
        article["trendUrl"] = str(payload.get("trendUrl") or article.get("trendUrl") or "")
        article["tag"] = str(payload.get("tag") or article.get("tag") or "prompt")
        if payload.get("section"):
            article["section"] = str(payload["section"])
        article["ownerUserId"] = payload.get("ownerUserId")
        article["status"] = article.get("status") or "published"
        is_x_article = payload.get("sourcePolicy") == "x_response"
        # Website articles must be complete when the job reports done. The old
        # pipeline selected the image before returning the article; deferring it
        # caused clients to permanently cache an image-less result.
        if not is_x_article and not article.get("image"):
            _attach_image(article, persist=False)
        queries.save_generated_article(article)
        queries.update_article_generation_job(
            job_id,
            status="saved",
            article_id=str(article["id"]),
        )
        set_build_progress(
            job_id,
            active=False,
            stage="done",
            stage_label="Done",
            article=article,
            draft_text="\n\n".join(article.get("body") or []),
            draft_headline=article.get("headline") or "",
            error=None,
        )
        if is_x_article and not article.get("image"):
            _image_executor.submit(_attach_image, dict(article))
        return True
    except Exception as exc:
        _fail_job(job_id, exc)
        return True


def process_next_job(*, lane: str = "all") -> bool:
    """Synchronous one-shot path used by tests and `--once`."""
    claimed = queries.claim_next_article_generation_job(lane=lane)
    if claimed:
        _prepare_claimed_job(claimed)
    ready = queries.claim_ready_article_generation_job(lane=lane)
    if ready:
        return _generate_claimed_job(ready)
    return bool(claimed)


def run_forever(*, poll_seconds: float = 1.0, lane: str = "all") -> None:
    # Website and X workers claim disjoint durable lanes. Sourcing remains
    # parallel inside each worker while generation is serialized per lane.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="article-source") as source_pool:
        sourcing = set()
        last_stale_cleanup = 0.0
        while True:
            now = time.monotonic()
            if now - last_stale_cleanup >= 60:
                expired = queries.expire_stale_background_article_jobs()
                if expired:
                    logger.warning("Expired %s stale background article job(s)", expired)
                last_stale_cleanup = now
            sourcing = {future for future in sourcing if not future.done()}
            while len(sourcing) < 2:
                claimed = queries.claim_next_article_generation_job(lane=lane)
                if not claimed:
                    break
                sourcing.add(source_pool.submit(_prepare_claimed_job, claimed))
            ready = queries.claim_ready_article_generation_job(lane=lane)
            if ready:
                _generate_claimed_job(ready)
                continue
            if not sourcing:
                time.sleep(max(0.1, poll_seconds))
            else:
                time.sleep(min(max(0.1, poll_seconds), 0.25))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Signal article-generation queue lane")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--lane", choices=("all", "website", "x"), default="all")
    args = parser.parse_args()
    if args.once:
        process_next_job(lane=args.lane)
        return
    run_forever(poll_seconds=args.poll_seconds, lane=args.lane)


if __name__ == "__main__":
    main()
