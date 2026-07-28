from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Callable

from app.config import settings
from app.db import queries
from app.policy.prompt_filter import prompt_is_blocked
from app.processing.article_writer import ZenArticleUnavailable, write_article_from_prompt
from app.x.client import XApiNotConfigured, get_x_client
from app.x.filter import filter_candidates, is_actionable_candidate
from app.x.models import XCandidate, XSharePackage
from app.x.reply import article_public_url, build_prompt, share_intent_url, x_reply_text

logger = logging.getLogger(__name__)


def _is_specific_prompt(prompt: str) -> bool:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'&.-]*", prompt or "")
    if len(words) >= 4:
        return True
    if len(words) >= 3 and len(prompt or "") >= 24:
        return True
    return False


def _candidates_from_signal_topics(limit: int = 10) -> list[XCandidate]:
    """Fallback discovery when X API is not wired yet."""
    topics = queries.list_trending_topics(limit=max(limit, 5)) or []
    out: list[XCandidate] = []
    for row in topics:
        name = str(
            row.get("entity_text")
            or row.get("name")
            or row.get("topic")
            or row.get("label")
            or ""
        ).strip()
        if not name:
            continue
        count = float(row.get("mentions") or row.get("count") or 0)
        entity_type = str(row.get("entity_type") or "topic").strip()
        out.append(
            XCandidate(
                topic=name,
                snippet=f"Signal desk {entity_type} mentioned about {int(count) or 1} times recently.",
                prompt=name,
                source="signal-internal",
                tag="x-trend",
                score=count,
                provider="signal-internal",
            )
        )
    return out[:limit]


def discover_candidates(
    *,
    limit: int = 8,
    query: str = "",
    prefer_x: bool = True,
) -> tuple[list[XCandidate], str]:
    """
    Discover candidates for the X pipeline.

    Order:
      1. Explicit query → X recent search
      2. Signal desk topics → X recent search for each (no trends API)
      3. Signal desk topics alone
    """
    client = get_x_client()
    if query.strip():
        try:
            hits = client.search_recent(query.strip(), limit=limit)
            if hits:
                return hits[:limit], "x-api-search"
        except (XApiNotConfigured, Exception) as exc:
            logger.info("X search unavailable for query, falling back: %s", exc)

    desk = _candidates_from_signal_topics(limit=max(limit, 5))
    if prefer_x and desk and client.read_configured():
        searched: list[XCandidate] = []
        seen_ids: set[str] = set()
        for topic in desk[: min(5, len(desk))]:
            try:
                hits = client.search_recent(topic.topic, limit=max(2, limit // 2))
            except Exception as exc:
                logger.info("X search seed failed for %s: %s", topic.topic, exc)
                continue
            for hit in hits:
                if hit.post_id and hit.post_id in seen_ids:
                    continue
                if hit.post_id:
                    seen_ids.add(hit.post_id)
                # Keep the desk topic as the article prompt seed when useful.
                if not hit.prompt:
                    hit.prompt = topic.topic
                searched.append(hit)
                if len(searched) >= limit:
                    return searched[:limit], "x-api-search-seeded"
        if searched:
            return searched[:limit], "x-api-search-seeded"

    # Trends intentionally unused — Signal desk topics are the non-X fallback.
    return desk[:limit], "signal-internal"


def write_article_for_candidate(
    candidate: XCandidate,
    *,
    mode: str = "fast",
    limit: int = 12,
    write_fn: Callable[..., dict] | None = None,
) -> XSharePackage:
    """Write + save a sourced article and return a ready-to-share package."""
    is_direct_prompt = candidate.provider == "manual-prompt" and bool(candidate.prompt.strip())
    if not is_direct_prompt:
        ok, reason = is_actionable_candidate(candidate)
        if not ok:
            return XSharePackage(
                status="skipped",
                article_url="",
                reply_text="",
                trend_url=candidate.trend_url,
                candidate=candidate.to_dict(),
                error=reason,
            )

    prompt_seed = re.sub(r"\s+", " ", candidate.prompt or "").strip()
    prompt_seed = prompt_seed[:2000 if is_direct_prompt else 240].rstrip()
    if is_direct_prompt:
        prompt = prompt_seed
    elif prompt_seed and _is_specific_prompt(prompt_seed):
        prompt = prompt_seed
    else:
        try:
            prompt = build_prompt(candidate.topic, candidate.snippet, candidate.prompt)
        except ValueError as exc:
            return XSharePackage(
                status="error",
                article_url="",
                reply_text="",
                trend_url=candidate.trend_url,
                candidate=candidate.to_dict(),
                error=str(exc),
            )

    blocked = prompt_is_blocked(prompt)
    if blocked.blocked:
        return XSharePackage(
            status="blocked",
            article_url="",
            reply_text="",
            trend_url=candidate.trend_url,
            candidate=candidate.to_dict(),
            error=f"prompt_blocked:{blocked.source}",
        )

    build_id = f"build-{uuid.uuid4().hex}"
    writer = write_fn or write_article_from_prompt
    try:
        article = writer(prompt, limit=limit, mode=mode, build_id=build_id)
    except ZenArticleUnavailable as exc:
        return XSharePackage(
            status="error",
            article_url="",
            reply_text="",
            trend_url=candidate.trend_url,
            candidate=candidate.to_dict(),
            error=str(exc),
        )
    except Exception as exc:
        logger.exception("X pipeline article write failed")
        return XSharePackage(
            status="error",
            article_url="",
            reply_text="",
            trend_url=candidate.trend_url,
            candidate=candidate.to_dict(),
            error=str(exc) or "article_write_failed",
        )

    article["buildId"] = build_id
    # Public byline should read like a normal Signal article, not "x-agent".
    article["source"] = "Signal desk"
    article["trendUrl"] = candidate.trend_url
    article["tag"] = candidate.tag or "x-trend"
    article["ownerUserId"] = None
    article["status"] = article.get("status") or "published"
    queries.save_generated_article(article)

    article_url = article_public_url(str(article["id"]))
    reply = x_reply_text(article, article_url)
    return XSharePackage(
        status="ready_to_post",
        article_url=article_url,
        reply_text=reply,
        trend_url=candidate.trend_url,
        candidate=candidate.to_dict(),
        article=article,
        share={
            "intentUrl": share_intent_url(
                article_url,
                article.get("headline") or "",
                reply_text=reply,
                in_reply_to_id=candidate.post_id,
            ),
            "postId": candidate.post_id,
        },
    )


def maybe_share_package(
    package: XSharePackage,
    *,
    dry_run: bool | None = None,
    auto_post: bool | None = None,
) -> XSharePackage:
    """Optionally post/reply via XClient. Defaults to dry-run until you enable posting."""
    if package.status != "ready_to_post":
        return package

    do_auto = settings.x_auto_post if auto_post is None else bool(auto_post)
    use_dry = settings.x_dry_run if dry_run is None else bool(dry_run)

    if not do_auto and use_dry:
        # Still record a dry-run share result so callers see the full contract.
        result = get_x_client().post_tweet(package.reply_text, dry_run=True)
        package.share = {
            **(package.share or {}),
            **result.to_dict(),
            "autoPost": False,
        }
        return package

    if not do_auto:
        package.share = {
            **(package.share or {}),
            "ok": True,
            "posted": False,
            "dry_run": False,
            "autoPost": False,
            "message": "Share package ready; auto-post disabled (SIGNAL_X_AUTO_POST=false).",
        }
        return package

    client = get_x_client()
    post_id = str((package.share or {}).get("postId") or "")
    if post_id:
        result = client.reply_to_post(post_id, package.reply_text, dry_run=use_dry)
    else:
        result = client.post_tweet(package.reply_text, dry_run=use_dry)
    package.share = {**(package.share or {}), **result.to_dict(), "autoPost": True}
    if result.ok and (result.posted or result.dry_run):
        package.status = "shared" if result.posted else "ready_to_post"
    elif not result.ok:
        package.status = "share_failed"
        package.error = result.message
    return package


def run_x_pipeline(
    *,
    max_articles: int = 3,
    discover_limit: int = 10,
    query: str = "",
    direct_prompt: str = "",
    mode: str = "fast",
    source_limit: int = 12,
    dry_run: bool | None = None,
    auto_post: bool | None = None,
    candidates: list[XCandidate] | None = None,
    write_fn: Callable[..., dict] | None = None,
) -> dict[str, Any]:
    """
    Full loop minus live X API:

    1. Discover trends (X stub → Signal-internal fallback)
    2. Filter actionable topics
    3. Write sourced articles
    4. Build durable frontend links + reply text
    5. Optionally dry-run / post via XClient stub
    """
    provider = "manual"
    cleaned_prompt = re.sub(r"\s+", " ", direct_prompt or "").strip()[:2000].rstrip()
    if cleaned_prompt:
        candidates = [
            XCandidate(
                topic=cleaned_prompt,
                prompt=cleaned_prompt,
                source="x-agent",
                tag="x-trend",
                provider="manual-prompt",
            )
        ]
        provider = "manual-prompt"
    elif candidates is None:
        candidates, provider = discover_candidates(limit=discover_limit, query=query)
    else:
        provider = (
            "manual-prompt"
            if candidates and all(candidate.provider == "manual-prompt" for candidate in candidates)
            else "manual"
        )

    actionable = (
        candidates
        if provider == "manual-prompt"
        else filter_candidates(candidates, limit=max(discover_limit, max_articles))
    )
    packages: list[dict[str, Any]] = []
    ready_count = 0
    for candidate in actionable:
        package = write_article_for_candidate(
            candidate,
            mode=mode,
            limit=source_limit,
            write_fn=write_fn,
        )
        package = maybe_share_package(package, dry_run=dry_run, auto_post=auto_post)
        package_dict = package.to_dict()
        packages.append(package_dict)
        if package_dict.get("status") in {"ready_to_post", "shared"}:
            ready_count += 1
            if ready_count >= max_articles:
                break

    ready = [p for p in packages if p.get("status") in {"ready_to_post", "shared"}]
    return {
        "status": "ok" if ready else "empty",
        "provider": provider,
        "xClient": get_x_client().status(),
        "discovered": len(candidates),
        "selected": len(actionable),
        "written": len(ready),
        "packages": packages,
        "publicArticleBaseUrl": settings.public_article_base_url,
    }
