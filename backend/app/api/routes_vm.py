from __future__ import annotations

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

MAX_VM_POSTS = 50
MAX_VM_TEXT_CHARS = 2_000


class VMPost(BaseModel):
    url: str = ""
    text: str = ""

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


@router.post("/vm")
def create_vm_draft(request: Request, payload: list[VMPost]):
    """
    Convert a batch of X posts into a sourced Signal article and return the
    X intent URL used by the admin desk's "Open in X" action.
    """
    _check_article_rate_limit(_client_rate_key(request, "vm"))
    if not payload:
        raise HTTPException(status_code=422, detail="Provide at least one post")
    if len(payload) > MAX_VM_POSTS:
        raise HTTPException(status_code=422, detail=f"Provide no more than {MAX_VM_POSTS} posts")

    posts = [{"url": post.url, "text": post.text} for post in payload if post.text]
    if not posts:
        raise HTTPException(status_code=422, detail="At least one post must include text")

    prompt = generic_news_prompt_from_x_posts_with_gemini(posts)
    if not prompt:
        raise HTTPException(status_code=503, detail=describe_last_gemini_error())

    package = write_article_for_candidate(
        XCandidate(
            topic=prompt,
            prompt=prompt,
            source="vm",
            tag="x-trend",
            provider="manual-prompt",
        ),
        mode="fast",
        limit=12,
    )
    if package.status != "ready_to_post":
        status_code = 422 if package.status in {"blocked", "skipped"} else 503
        raise HTTPException(status_code=status_code, detail=package.error or "Could not draft article")

    intent_url = str((package.share or {}).get("intentUrl") or "").strip()
    if not intent_url:
        raise HTTPException(status_code=503, detail="The X draft link was not created")
    return {"url": intent_url}
