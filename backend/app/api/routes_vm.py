from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, validator

from app.api.routes_articles import _check_article_rate_limit, _client_rate_key
from app.llm.gemini_writer import (
    describe_last_gemini_error,
    generic_news_prompt_from_x_posts_with_gemini,
)
from app.x.models import XCandidate
from app.x.pipeline import write_article_for_candidate

router = APIRouter()

MAX_VM_POSTS = 5
MAX_VM_TEXT_CHARS = 2_000
MAX_VM_CONTEXT_CHARS = 1_000


class VMPost(BaseModel):
    url: str = ""
    text: str = ""
    reason: str = ""
    angle: str = ""
    source_assessment: str = ""

    @validator("url")
    def url_size(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) > 500:
            raise ValueError("url must be 500 characters or fewer")
        return cleaned

    @validator("text")
    def text_size(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) > MAX_VM_TEXT_CHARS:
            raise ValueError(f"text must be {MAX_VM_TEXT_CHARS} characters or fewer")
        return cleaned

    @validator("reason", "angle", "source_assessment")
    def context_size(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if len(cleaned) > MAX_VM_CONTEXT_CHARS:
            raise ValueError(f"context fields must be {MAX_VM_CONTEXT_CHARS} characters or fewer")
        return cleaned


def _x_post_id(url: str) -> str:
    match = re.search(r"(?:x|twitter)\.com/[^/]+/status/(\d+)", url or "", flags=re.IGNORECASE)
    return match.group(1) if match else ""


@router.post("/vm")
def create_vm_draft(request: Request, payload: list[VMPost]):
    """
    Convert each X post into its own sourced Signal article and return the X
    reply-intent URLs used by the admin desk's "Open in X" action.
    """
    _check_article_rate_limit(_client_rate_key(request, "vm"))
    if not payload:
        raise HTTPException(status_code=422, detail="Provide at least one post")
    if len(payload) > MAX_VM_POSTS:
        raise HTTPException(status_code=422, detail=f"Provide no more than {MAX_VM_POSTS} posts")

    reply_links: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    generation_attempted = False

    for post in payload:
        post_id = _x_post_id(post.url)
        if not post.text:
            errors.append({"url": post.url, "error": "Post text is required"})
            continue
        if not post_id:
            errors.append({"url": post.url, "error": "A valid X status URL is required"})
            continue

        generation_attempted = True
        prompt = generic_news_prompt_from_x_posts_with_gemini([post.model_dump()])
        if not prompt:
            errors.append({"url": post.url, "error": describe_last_gemini_error()})
            continue

        package = write_article_for_candidate(
            XCandidate(
                topic=prompt,
                prompt=prompt,
                trend_url=post.url,
                post_id=post_id,
                source="vm",
                tag="x-trend",
                provider="manual-prompt",
            ),
            mode="fast",
            limit=12,
        )
        if package.status != "ready_to_post":
            errors.append({"url": post.url, "error": package.error or "Could not draft article"})
            continue

        intent_url = str((package.share or {}).get("intentUrl") or "").strip()
        if not intent_url:
            errors.append({"url": post.url, "error": "The X reply link was not created"})
            continue
        reply_links.append({"url": post.url, "reply_url": intent_url})

    if not reply_links:
        detail = errors[0]["error"] if len(errors) == 1 else {"message": "No reply links were created", "errors": errors}
        raise HTTPException(status_code=503 if generation_attempted else 422, detail=detail)

    response: dict[str, list[dict[str, str]]] = {"reply_links": reply_links}
    if errors:
        response["errors"] = errors
    return response
