from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import queries


router = APIRouter()


@router.get("/stories")
def stories():
    return queries.list_stories()


@router.get("/stories/latest")
def latest_stories():
    return queries.list_stories()[:10]


@router.get("/stories/trending")
def trending_stories():
    return sorted(queries.list_stories(), key=lambda story: story["article_count"], reverse=True)[:10]


@router.get("/stories/{story_id}")
def story_detail(story_id: int):
    story = queries.get_story(story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    return story


@router.get("/stories/{story_id}/claims")
def story_claims(story_id: int):
    return queries.get_cluster_claims(story_id)


@router.get("/stories/{story_id}/consensus")
def story_consensus(story_id: int):
    return queries.list_consensus(story_id)

