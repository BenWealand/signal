from __future__ import annotations

from fastapi import APIRouter, Query

from app.db import queries


router = APIRouter()


@router.get("/search")
def search(q: str = Query(min_length=2)):
    return queries.search(q)


@router.get("/entities/{entity_name}")
def entity(entity_name: str):
    return queries.entity_articles(entity_name)

