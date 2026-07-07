from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db import queries


router = APIRouter()


@router.get("/stories")
def stories(limit: int = 30):
    return queries.list_stories(limit=min(max(limit, 1), 100))


@router.get("/stories/latest")
def latest_stories():
    return queries.list_stories(limit=10)


@router.get("/stories/trending")
def trending_stories():
    return sorted(queries.list_stories(limit=30), key=lambda story: story["article_count"], reverse=True)[:10]


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

