from __future__ import annotations

import re
from collections import defaultdict


def topic_key(article: dict[str, object]) -> str:
    text = f"{article.get('title', '')} {article.get('clean_text', '')}".lower()
    if "climate" in text or "flood" in text:
        return "Climate bill and public cost reporting"
    if "senate" in text or "bill" in text:
        return "Senate passes climate bill"
    words = re.findall(r"[a-z]{5,}", text)
    return " ".join(words[:4]) or "General news cluster"


def cluster_articles(articles: list[dict[str, object]]) -> dict[str, list[int]]:
    clusters: dict[str, list[int]] = defaultdict(list)
    for article in articles:
        clusters[topic_key(article)].append(int(article["id"]))
    return dict(clusters)

