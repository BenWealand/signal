from __future__ import annotations

import datetime
import json
from typing import Any

from app.db.connection import get_connection
from app.policy.prompt_filter import article_is_blocked
from app.processing.dedupe import normalize_title, probable_duplicate


def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, (datetime.datetime, datetime.date)):
            result[key] = value.isoformat()
    return result


def insert_article(article: dict[str, Any]) -> int:
    source_id = ensure_source(
        {
            "source_name": article["source_name"],
            "domain": article.get("domain", ""),
            "country": article.get("country", ""),
            "language": article.get("language", "en"),
            "source_type": article.get("source_type", "news"),
            "reliability_tier": article.get("reliability_tier", "standard"),
            "political_lean_optional": article.get("political_lean_optional", ""),
            "rss_url": article.get("rss_url", ""),
        }
    )
    normalized_title = normalize_title(article["title"])
    with get_connection() as conn:
        duplicate = find_duplicate_article(conn, {**article, "normalized_title": normalized_title})
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO articles
                (source_id, source_name, title, normalized_title, url, published_at, description,
                 raw_text, clean_text, topic, language, status, duplicate_of)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(url) DO NOTHING
                """,
                (
                    source_id,
                    article["source_name"],
                    article["title"],
                    normalized_title,
                    article["url"],
                    article.get("published_at"),
                    article.get("description", ""),
                    article["raw_text"],
                    article.get("clean_text"),
                    article.get("topic", ""),
                    article.get("language", "en"),
                    "duplicate" if duplicate else article.get("status", "new"),
                    duplicate["id"] if duplicate else None,
                ),
            )
            cur.execute("SELECT id FROM articles WHERE url = %s", (article["url"],))
            row = cur.fetchone()
            return int(row["id"])


def ensure_source(source: dict[str, Any]) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM sources WHERE source_name = %s", (source["source_name"],))
            row = cur.fetchone()
            if row:
                return int(row["id"])
            cur.execute(
                """
                INSERT INTO sources
                (source_name, domain, country, language, source_type, reliability_tier, political_lean_optional, rss_url, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    source["source_name"],
                    source.get("domain", ""),
                    source.get("country", ""),
                    source.get("language", "en"),
                    source.get("source_type", "news"),
                    source.get("reliability_tier", "standard"),
                    source.get("political_lean_optional", ""),
                    source.get("rss_url", ""),
                    1 if source.get("is_active", True) else 0,
                ),
            )
            return int(cur.fetchone()["id"])


def replace_sources(sources: list[dict[str, Any]]) -> None:
    for source in sources:
        ensure_source(source)


def list_sources(active_only: bool = False) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if active_only:
                cur.execute("SELECT * FROM sources WHERE is_active = 1 ORDER BY source_name")
            else:
                cur.execute("SELECT * FROM sources ORDER BY source_name")
            return [row_to_dict(row) for row in cur.fetchall()]


def find_duplicate_article(conn: Any, article: dict[str, Any]) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        if article.get("url"):
            cur.execute("SELECT * FROM articles WHERE url = %s", (article["url"],))
            row = cur.fetchone()
            if row:
                return row_to_dict(row)
        cur.execute(
            """
            SELECT * FROM articles
            WHERE normalized_title = %s
               OR (source_name = %s AND normalized_title = %s)
            ORDER BY published_at DESC
            LIMIT 20
            """,
            (
                article.get("normalized_title") or normalize_title(article.get("title", "")),
                article["source_name"],
                article.get("normalized_title") or normalize_title(article.get("title", "")),
            ),
        )
        candidates = [row_to_dict(r) for r in cur.fetchall()]
    for candidate in candidates:
        if probable_duplicate(article, candidate):
            return candidate
    return None


def list_articles(status: str | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if status:
                cur.execute("SELECT * FROM articles WHERE status = %s ORDER BY published_at DESC", (status,))
            else:
                cur.execute("SELECT * FROM articles ORDER BY published_at DESC")
            return [row_to_dict(row) for row in cur.fetchall()]


def list_articles_needing_processing() -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.* FROM articles a
                LEFT JOIN claims c ON c.article_id = a.id
                WHERE a.status = 'new'
                   OR (a.status = 'processed' AND c.id IS NULL)
                   OR (a.status = 'processed' AND (c.source_name IS NULL OR c.source_name = ''))
                GROUP BY a.id
                ORDER BY a.published_at DESC
                """
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def get_article(article_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM articles WHERE id = %s", (article_id,))
            return row_to_dict(cur.fetchone())


def articles_by_source(source_name: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM articles WHERE lower(source_name) = lower(%s) ORDER BY published_at DESC",
                (source_name,),
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def update_article_processing(article_id: int, clean_text: str, status: str) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE articles SET clean_text = %s, status = %s WHERE id = %s",
                (clean_text, status, article_id),
            )


def replace_entities(article_id: int, entities: list[dict[str, Any]]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM entities WHERE article_id = %s", (article_id,))
            cur.executemany(
                """
                INSERT INTO entities (article_id, entity_text, entity_type, start_char, end_char)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        article_id,
                        item["text"],
                        item["type"],
                        item.get("start_char", 0),
                        item.get("end_char", 0),
                    )
                    for item in entities
                ],
            )


def replace_claims(article_id: int, claims: list[dict[str, Any]]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT source_name FROM articles WHERE id = %s", (article_id,))
            article = cur.fetchone()
            source_name = article["source_name"] if article else ""
            cur.execute("DELETE FROM claims WHERE article_id = %s", (article_id,))
            cur.executemany(
                """
                INSERT INTO claims (article_id, claim_text, claim_type, entities, source_name, claim_order, confidence_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        article_id,
                        item["text"],
                        item.get("claim_type", "event"),
                        json.dumps(item.get("entities", [])),
                        source_name,
                        index,
                        item.get("confidence_score", 0.75),
                    )
                    for index, item in enumerate(claims, start=1)
                ],
            )


def create_cluster(topic_label: str, article_ids: list[int]) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM story_clusters WHERE topic_label = %s", (topic_label,))
            row = cur.fetchone()
            if row:
                cluster_id = int(row["id"])
            else:
                cur.execute(
                    "INSERT INTO story_clusters (topic_label) VALUES (%s) RETURNING id",
                    (topic_label,),
                )
                cluster_id = int(cur.fetchone()["id"])

            cur.executemany(
                """
                INSERT INTO story_cluster_articles (story_cluster_id, article_id)
                VALUES (%s, %s)
                ON CONFLICT(story_cluster_id, article_id) DO NOTHING
                """,
                [(cluster_id, article_id) for article_id in article_ids],
            )
            cur.execute(
                "UPDATE story_clusters SET updated_at = NOW() WHERE id = %s",
                (cluster_id,),
            )
            return cluster_id


def get_cluster_articles(cluster_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.* FROM articles a
                JOIN story_cluster_articles sca ON sca.article_id = a.id
                WHERE sca.story_cluster_id = %s
                ORDER BY a.published_at DESC
                """,
                (cluster_id,),
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def get_cluster_claims(cluster_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.*, a.source_name, a.title, a.url FROM claims c
                JOIN articles a ON a.id = c.article_id
                JOIN story_cluster_articles sca ON sca.article_id = a.id
                WHERE sca.story_cluster_id = %s
                ORDER BY c.claim_order
                """,
                (cluster_id,),
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def replace_consensus_claims(cluster_id: int, claims: list[dict[str, Any]]) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM consensus_claims WHERE story_cluster_id = %s", (cluster_id,))
            cur.executemany(
                """
                INSERT INTO consensus_claims
                (story_cluster_id, claim_text, support_count, source_list, status, source_diversity_score, confidence_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        cluster_id,
                        item["claim_text"],
                        item["support_count"],
                        json.dumps(item["sources"]),
                        item["status"],
                        item.get("source_diversity_score", 0),
                        item.get("confidence_score", 0),
                    )
                    for item in claims
                ],
            )


def save_summary(cluster_id: int, summary_text: str, model_name: str = "local-rule-mvp") -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO generated_summaries (story_cluster_id, summary_text, model_name)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (cluster_id, summary_text, model_name),
            )
            return int(cur.fetchone()["id"])


def list_stories(limit: int = 30) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  sc.id,
                  sc.topic_label,
                  sc.created_at,
                  sc.updated_at,
                  COUNT(DISTINCT sca.article_id) AS article_count,
                  COALESCE((
                    SELECT gs.summary_text
                    FROM generated_summaries gs
                    WHERE gs.story_cluster_id = sc.id
                    ORDER BY gs.created_at DESC, gs.id DESC
                    LIMIT 1
                  ), '') AS summary_text
                FROM story_clusters sc
                LEFT JOIN story_cluster_articles sca ON sca.story_cluster_id = sc.id
                GROUP BY sc.id
                ORDER BY sc.updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def get_story(story_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT sc.*, COALESCE(gs.summary_text, '') AS summary_text, gs.model_name
                FROM story_clusters sc
                LEFT JOIN generated_summaries gs ON gs.story_cluster_id = sc.id
                WHERE sc.id = %s
                ORDER BY gs.created_at DESC
                LIMIT 1
                """,
                (story_id,),
            )
            story = cur.fetchone()
    result = row_to_dict(story)
    if result:
        result["articles"] = get_cluster_articles(story_id)
        result["consensus"] = list_consensus(story_id)
    return result


def list_consensus(story_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM consensus_claims WHERE story_cluster_id = %s ORDER BY support_count DESC",
                (story_id,),
            )
            items = [row_to_dict(row) for row in cur.fetchall()]
    for item in items:
        item["source_list"] = json.loads(item["source_list"])
    return items


def search(q: str, *, days: int | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """
    Search ingested articles. When `days` is set, prefer coverage from the
    recent window so Fast mode can draft from today's desk cache first.
    """
    term = f"%{q}%"
    safe_limit = min(max(limit, 1), 50)
    with get_connection() as conn:
        with conn.cursor() as cur:
            if days and days > 0:
                cur.execute(
                    """
                    SELECT id, source_name, title, url, published_at, clean_text, raw_text, description, topic
                    FROM articles
                    WHERE (title ILIKE %s OR clean_text ILIKE %s OR description ILIKE %s OR raw_text ILIKE %s)
                      AND COALESCE(published_at, created_at) > NOW() - (%s || ' days')::interval
                    ORDER BY COALESCE(published_at, created_at) DESC
                    LIMIT %s
                    """,
                    (term, term, term, term, str(int(days)), safe_limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, source_name, title, url, published_at, clean_text, raw_text, description, topic
                    FROM articles
                    WHERE title ILIKE %s OR clean_text ILIKE %s OR description ILIKE %s OR raw_text ILIKE %s
                    ORDER BY COALESCE(published_at, created_at) DESC
                    LIMIT %s
                    """,
                    (term, term, term, term, safe_limit),
                )
            return [row_to_dict(row) for row in cur.fetchall()]


def entity_articles(entity_name: str) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT a.* FROM articles a
                JOIN entities e ON e.article_id = a.id
                WHERE lower(e.entity_text) = lower(%s)
                ORDER BY a.published_at DESC
                """,
                (entity_name,),
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def save_generated_article(article: dict[str, Any]) -> str:
    if article_is_blocked(article).blocked:
        delete_generated_article(str(article["id"]))
        return str(article["id"])
    section = str(article.get("section") or "").strip().lower() or classify_article_section(article)
    with get_connection() as conn:
        with conn.cursor() as cur:
            _ensure_generated_article_metadata_columns(cur)
            cur.execute(
                """
                INSERT INTO generated_articles
                (id, owner_user_id, source, tag, trend_url, prompt, headline, dek, summary, body, facts,
                 terms, sources, source_links, consensus, source_count, denied_for_bias,
                 fairness_score, accuracy_score, score_metadata, generation_mode, source_quality,
                 consensus_level, used_live_sources, fallback_reason, image, section, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(id) DO UPDATE SET
                  owner_user_id = COALESCE(generated_articles.owner_user_id, EXCLUDED.owner_user_id),
                  source = EXCLUDED.source,
                  tag = EXCLUDED.tag,
                  trend_url = EXCLUDED.trend_url,
                  prompt = EXCLUDED.prompt,
                  headline = EXCLUDED.headline,
                  dek = EXCLUDED.dek,
                  summary = EXCLUDED.summary,
                  body = EXCLUDED.body,
                  facts = EXCLUDED.facts,
                  terms = EXCLUDED.terms,
                  sources = EXCLUDED.sources,
                  source_links = EXCLUDED.source_links,
                  consensus = EXCLUDED.consensus,
                  source_count = EXCLUDED.source_count,
                  denied_for_bias = EXCLUDED.denied_for_bias,
                  fairness_score = EXCLUDED.fairness_score,
                  accuracy_score = EXCLUDED.accuracy_score,
                  score_metadata = EXCLUDED.score_metadata,
                  generation_mode = EXCLUDED.generation_mode,
                  source_quality = EXCLUDED.source_quality,
                  consensus_level = EXCLUDED.consensus_level,
                  used_live_sources = EXCLUDED.used_live_sources,
                  fallback_reason = EXCLUDED.fallback_reason,
                  image = EXCLUDED.image,
                  section = EXCLUDED.section,
                  status = EXCLUDED.status
                """,
                (
                    article["id"],
                    article.get("ownerUserId"),
                    article.get("source", "news-desk"),
                    article.get("tag", "trend"),
                    article.get("trendUrl", ""),
                    article["prompt"],
                    article["headline"],
                    article["dek"],
                    article["summary"],
                    json.dumps(article.get("body", [])),
                    json.dumps(article.get("facts", [])),
                    json.dumps(article.get("terms", [])),
                    json.dumps(article.get("sources", [])),
                    json.dumps(article.get("sourceLinks", [])),
                    json.dumps(article.get("consensus", [])),
                    article.get("sourceCount", 0),
                    article.get("deniedForBias", 0),
                    article.get("fairnessScore", 0),
                    article.get("accuracyScore", 0),
                    json.dumps(article.get("scoreMetadata", {})),
                    article.get("generation_mode", ""),
                    json.dumps(article.get("source_quality", {})),
                    article.get("consensus_level", ""),
                    1 if article.get("used_live_sources") else 0,
                    article.get("fallback_reason", ""),
                    json.dumps(article.get("image") or {}),
                    section,
                    article.get("status", "published"),
                    article.get("createdAt"),
                ),
            )
            article["section"] = section
            return str(article["id"])


_GENERATED_ARTICLE_METADATA_COLUMNS = {
    "owner_user_id": "INTEGER REFERENCES users(id)",
    "source_links": "TEXT DEFAULT '[]'",
    "consensus": "TEXT DEFAULT '[]'",
    "score_metadata": "TEXT DEFAULT '{}'",
    "generation_mode": "TEXT DEFAULT ''",
    "source_quality": "TEXT DEFAULT '{}'",
    "consensus_level": "TEXT DEFAULT ''",
    "used_live_sources": "SMALLINT DEFAULT 0",
    "fallback_reason": "TEXT DEFAULT ''",
    "image": "TEXT DEFAULT '{}'",
    "section": "TEXT DEFAULT ''",
}


def _ensure_generated_article_metadata_columns(cur: Any) -> None:
    for name, definition in _GENERATED_ARTICLE_METADATA_COLUMNS.items():
        cur.execute(f"ALTER TABLE generated_articles ADD COLUMN IF NOT EXISTS {name} {definition}")


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _decode_generated_article(row: Any) -> dict[str, Any]:
    item = row_to_dict(row)
    if not item:
        return {}
    decoded = {
        "id": item["id"],
        "ownerUserId": item.get("owner_user_id"),
        "source": item["source"],
        "tag": item["tag"],
        "trendUrl": item["trend_url"],
        "prompt": item["prompt"],
        "headline": item["headline"],
        "dek": item["dek"],
        "summary": item["summary"],
        "body": _json_loads(item["body"], []),
        "facts": _json_loads(item["facts"], []),
        "terms": _json_loads(item["terms"], []),
        "sources": _json_loads(item["sources"], []),
        "sourceLinks": _json_loads(item.get("source_links"), []),
        "consensus": _json_loads(item.get("consensus"), []),
        "sourceCount": item["source_count"],
        "deniedForBias": item["denied_for_bias"],
        "fairnessScore": item["fairness_score"],
        "accuracyScore": item["accuracy_score"],
        "scoreMetadata": _json_loads(item.get("score_metadata"), {}),
        "generation_mode": item.get("generation_mode", ""),
        "source_quality": _json_loads(item.get("source_quality"), {}),
        "consensus_level": item.get("consensus_level", ""),
        "used_live_sources": bool(item.get("used_live_sources", 0)),
        "fallback_reason": item.get("fallback_reason", ""),
        "image": _json_loads(item.get("image"), {}),
        "section": str(item.get("section") or "").lower(),
        "status": item["status"],
        "createdAt": item["created_at"],
    }
    if not decoded["section"]:
        decoded["section"] = classify_article_section(decoded)
    return decoded


_GENERATED_FEED_COLUMNS = """
id, source, tag, trend_url, prompt, headline, dek, summary, sources,
source_count, denied_for_bias, fairness_score, accuracy_score,
generation_mode, used_live_sources, fallback_reason, section, status, created_at
"""

FEED_SECTION_SLUGS = ("world", "politics", "sports", "markets", "technology", "climate")


def _decode_feed_article(row: Any, *, trend_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    item = row_to_dict(row)
    if not item:
        return {}
    decoded = {
        "id": item["id"],
        "source": item["source"],
        "tag": item["tag"],
        "trendUrl": item["trend_url"],
        "prompt": item["prompt"],
        "headline": item["headline"],
        "dek": item["dek"],
        "summary": item["summary"],
        "sources": _json_loads(item.get("sources"), []),
        "sourceCount": item["source_count"],
        "deniedForBias": item["denied_for_bias"],
        "fairnessScore": item["fairness_score"],
        "accuracyScore": item["accuracy_score"],
        "generation_mode": item.get("generation_mode", ""),
        "used_live_sources": bool(item.get("used_live_sources", 0)),
        "fallback_reason": item.get("fallback_reason", ""),
        "section": item.get("section", ""),
        "status": item["status"],
        "createdAt": item["created_at"],
        "preview": True,
    }
    if trend_metrics:
        decoded["trendMetrics"] = trend_metrics
    return decoded


def _filter_feed_articles(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for item in items:
        if article_is_blocked(item).blocked:
            continue
        filtered.append(item)
        if len(filtered) >= limit:
            break
    return filtered


def list_generated_articles(limit: int = 25) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_GENERATED_FEED_COLUMNS}
                FROM generated_articles
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (max(limit * 3, limit),),
            )
            items = [_decode_feed_article(row) for row in cur.fetchall()]
            return _filter_feed_articles(items, limit)


def get_generated_article(article_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM generated_articles WHERE id = %s", (article_id,))
            article = _decode_generated_article(cur.fetchone())
            return {} if article and article_is_blocked(article).blocked else article


def list_recent_x_feed_articles(hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
    """Return unique Zen feed articles plus their latest successful X share."""
    safe_hours = min(max(int(hours or 24), 1), 168)
    safe_limit = min(max(int(limit or 100), 1), 200)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  ga.*,
                  shared.x_post_id AS shared_x_post_id,
                  shared.x_post_url AS shared_x_post_url,
                  shared.reply_to_post_id AS shared_reply_to_post_id,
                  shared.reply_url AS shared_reply_url,
                  shared.created_at AS shared_at
                FROM generated_articles ga
                LEFT JOIN LATERAL (
                  SELECT x_post_id, x_post_url, reply_to_post_id, reply_url, created_at
                  FROM x_article_shares
                  WHERE article_id = ga.id AND status = 'posted'
                  ORDER BY created_at DESC
                  LIMIT 1
                ) shared ON TRUE
                WHERE ga.status = 'published'
                  AND ga.generation_mode IN ('fast', 'thorough')
                  AND ga.created_at >= NOW() - (%s * INTERVAL '1 hour')
                ORDER BY ga.created_at DESC
                LIMIT %s
                """,
                (safe_hours, safe_limit * 3),
            )
            articles: list[dict[str, Any]] = []
            for row in cur.fetchall():
                raw = row_to_dict(row)
                article = _decode_generated_article(raw)
                if not article or article_is_blocked(article).blocked:
                    continue
                article["xShare"] = {
                    "posted": bool(raw.get("shared_x_post_id")),
                    "postId": raw.get("shared_x_post_id") or "",
                    "postUrl": raw.get("shared_x_post_url") or "",
                    "replyToPostId": raw.get("shared_reply_to_post_id") or "",
                    "replyUrl": raw.get("shared_reply_url") or "",
                    "postedAt": raw.get("shared_at"),
                }
                articles.append(article)
                if len(articles) >= safe_limit:
                    break
            return articles


def get_posted_x_share(article_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM x_article_shares
                WHERE article_id = %s AND status = 'posted'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (article_id,),
            )
            return row_to_dict(cur.fetchone())


def record_x_article_share(
    article_id: str,
    draft_text: str,
    *,
    status: str,
    x_post_id: str = "",
    x_post_url: str = "",
    reply_to_post_id: str = "",
    reply_url: str = "",
    error: str = "",
) -> dict[str, Any]:
    if status not in {"posted", "dry_run", "failed"}:
        raise ValueError("Invalid X article share status")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO x_article_shares
                  (article_id, draft_text, status, x_post_id, x_post_url,
                   reply_to_post_id, reply_url, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (article_id) WHERE status = 'posted' DO NOTHING
                RETURNING *
                """,
                (
                    article_id,
                    draft_text,
                    status,
                    x_post_id,
                    x_post_url,
                    reply_to_post_id,
                    reply_url,
                    error,
                ),
            )
            saved = row_to_dict(cur.fetchone())
            if saved:
                return saved
            cur.execute(
                """
                SELECT * FROM x_article_shares
                WHERE article_id = %s AND status = 'posted'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (article_id,),
            )
            return row_to_dict(cur.fetchone())


def delete_generated_article(article_id: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM saved_stories WHERE story_id = %s", (article_id,))
            cur.execute("DELETE FROM user_history WHERE article_id = %s", (article_id,))
            cur.execute("DELETE FROM generated_articles WHERE id = %s", (article_id,))
            return int(cur.rowcount or 0)


def _delete_generated_article_cur(cur: Any, article_id: str) -> int:
    cur.execute("DELETE FROM saved_stories WHERE story_id = %s", (article_id,))
    cur.execute("DELETE FROM user_history WHERE article_id = %s", (article_id,))
    cur.execute("DELETE FROM generated_articles WHERE id = %s", (article_id,))
    return int(cur.rowcount or 0)


def purge_blacklisted_generated_articles(limit: int = 1000) -> dict[str, Any]:
    deleted: list[str] = []
    scanned = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM generated_articles
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            articles = [_decode_generated_article(row) for row in cur.fetchall()]
            scanned = len(articles)
            for article in articles:
                if article and article_is_blocked(article).blocked:
                    article_id = str(article["id"])
                    _delete_generated_article_cur(cur, article_id)
                    deleted.append(article_id)
    return {"scanned": scanned, "deleted": len(deleted), "articleIds": deleted}


def purge_legacy_generated_articles(limit: int = 1000) -> dict[str, Any]:
    """
    Remove generated articles that obviously predate the Zen-only policy.

    Older rows did not store a writer-provider field, so this intentionally
    purges only clear legacy/noncompliant rows instead of guessing.
    """
    deleted: list[str] = []
    scanned = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM generated_articles
                WHERE COALESCE(fallback_reason, '') <> ''
                   OR COALESCE(generation_mode, '') NOT IN ('fast', 'thorough')
                   OR COALESCE(used_live_sources, FALSE) = FALSE
                   OR COALESCE(body, '[]') IN ('', '[]', 'null')
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            articles = [_decode_generated_article(row) for row in cur.fetchall()]
            scanned = len(articles)
            for article in articles:
                if not article:
                    continue
                article_id = str(article["id"])
                _delete_generated_article_cur(cur, article_id)
                deleted.append(article_id)
    return {"scanned": scanned, "deleted": len(deleted), "articleIds": deleted}


def upsert_user(
    name: str,
    email: str,
    plan: str = "Reader",
    supabase_user_id: str | None = None,
    *,
    role: str = "reader",
    email_confirmed: bool = False,
    touch_login: bool = False,
) -> dict[str, Any]:
    role = (role or "reader").strip().lower()
    if role not in {"reader", "editor", "admin"}:
        role = "reader"
    confirmed = 1 if email_confirmed else 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            if supabase_user_id:
                cur.execute(
                    """
                    WITH updated AS (
                      UPDATE users
                      SET name = %s,
                          email = %s,
                          plan = %s,
                          role = %s,
                          supabase_user_id = %s,
                          email_confirmed = GREATEST(COALESCE(email_confirmed, 0), %s),
                          last_login_at = CASE WHEN %s THEN NOW() ELSE last_login_at END
                      WHERE email = %s OR supabase_user_id = %s
                      RETURNING *
                    ),
                    inserted AS (
                      INSERT INTO users (name, email, plan, role, supabase_user_id, email_confirmed, last_login_at)
                      SELECT %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() ELSE NULL END
                      WHERE NOT EXISTS (SELECT 1 FROM updated)
                      ON CONFLICT(email) DO UPDATE SET
                        name = EXCLUDED.name,
                        plan = EXCLUDED.plan,
                        role = EXCLUDED.role,
                        supabase_user_id = EXCLUDED.supabase_user_id,
                        email_confirmed = GREATEST(COALESCE(users.email_confirmed, 0), EXCLUDED.email_confirmed),
                        last_login_at = CASE
                          WHEN %s THEN NOW()
                          ELSE users.last_login_at
                        END
                      RETURNING *
                    )
                    SELECT * FROM updated
                    UNION ALL
                    SELECT * FROM inserted
                    LIMIT 1
                    """,
                    (
                        name,
                        email,
                        plan,
                        role,
                        supabase_user_id,
                        confirmed,
                        touch_login,
                        email,
                        supabase_user_id,
                        name,
                        email,
                        plan,
                        role,
                        supabase_user_id,
                        confirmed,
                        touch_login,
                        touch_login,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO users (name, email, plan, role, email_confirmed, last_login_at)
                    VALUES (%s, %s, %s, %s, %s, CASE WHEN %s THEN NOW() ELSE NULL END)
                    ON CONFLICT(email) DO UPDATE SET
                      name = EXCLUDED.name,
                      plan = EXCLUDED.plan,
                      role = EXCLUDED.role,
                      email_confirmed = GREATEST(COALESCE(users.email_confirmed, 0), EXCLUDED.email_confirmed),
                      last_login_at = CASE
                        WHEN %s THEN NOW()
                        ELSE users.last_login_at
                      END
                    RETURNING *
                    """,
                    (name, email, plan, role, confirmed, touch_login, touch_login),
                )
            return row_to_dict(cur.fetchone())


def get_user(user_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return row_to_dict(cur.fetchone())


def get_user_by_supabase_id(supabase_user_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE supabase_user_id = %s", (supabase_user_id,))
            return row_to_dict(cur.fetchone())


def get_user_by_email(email: str) -> dict[str, Any]:
    cleaned = (email or "").strip().lower()
    if not cleaned:
        return {}
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE LOWER(email) = %s", (cleaned,))
            return row_to_dict(cur.fetchone())


def set_user_role(user_id: int, role: str) -> dict[str, Any]:
    cleaned = (role or "reader").strip().lower()
    if cleaned not in {"reader", "editor", "admin"}:
        cleaned = "reader"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET role = %s,
                    plan = CASE WHEN %s = 'admin' THEN 'Admin' ELSE COALESCE(plan, 'Reader') END
                WHERE id = %s
                RETURNING *
                """,
                (cleaned, cleaned, user_id),
            )
            return row_to_dict(cur.fetchone())


def list_users(*, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 50), 1), 200)
    safe_offset = max(int(offset or 0), 0)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, email, plan, role, supabase_user_id, email_confirmed,
                       last_login_at, created_at
                FROM users
                ORDER BY created_at DESC NULLS LAST, id DESC
                LIMIT %s OFFSET %s
                """,
                (safe_limit, safe_offset),
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def count_users() -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM users")
            row = cur.fetchone()
            if not row:
                return 0
            data = row_to_dict(row)
            return int(data.get("count") or 0)


def save_story(user_id: int | None, story_id: str, title: str, source_count: int = 0) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id is not None:
                cur.execute(
                    """
                    INSERT INTO saved_stories (user_id, story_id, title, source_count)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(user_id, story_id) DO UPDATE SET
                      title = EXCLUDED.title,
                      source_count = EXCLUDED.source_count
                    RETURNING id
                    """,
                    (user_id, story_id, title, source_count),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO saved_stories (user_id, story_id, title, source_count)
                    VALUES (NULL, %s, %s, %s)
                    RETURNING id
                    """,
                    (story_id, title, source_count),
                )
            saved_id = int(cur.fetchone()["id"])
            cur.execute("SELECT owner_user_id FROM generated_articles WHERE id = %s", (story_id,))
            article = cur.fetchone()
            _create_notification(
                cur,
                article.get("owner_user_id") if article else None,
                "article_save",
                f"Your article was saved: {title}",
                article_id=story_id,
                actor_user_id=user_id,
                actor_name="Reader",
            )
            return saved_id


_SECTION_KEYWORDS: dict[str, list[str]] = {
    "world": ["international", "global", "foreign", "diplomacy", "world affairs", "nato", "conflict", "united nations"],
    "politics": ["congress", "senate", "legislation", "election", "government", "policy", "president", "political", "democrat", "republican"],
    "sports": ["sport", "sports", "athlete", "league", "championship", "olympic", "nba", "nfl", "mlb", "soccer", "football", "tennis"],
    "markets": ["market", "economy", "financial", "inflation", "trade", "bank", "gdp", "stock", "fed ", "interest rate"],
    "technology": ["technology", "artificial intelligence", " ai ", "semiconductor", "chip", "cybersecurity", "tech", "software", "digital"],
    "climate": ["climate", "weather", "flood", "hurricane", "renewable", "carbon", "environment", "energy", "wildfire"],
}

DEFAULT_ARTICLE_SECTION = "world"


def classify_article_section(article: dict[str, Any]) -> str:
    """
    Assign every article to exactly one topic. Scores each section by keyword
    hits across the article's prompt, headline, dek, summary, and terms;
    ties/misses fall back to the default section so no article is topicless.
    """
    terms = article.get("terms") or []
    text = " ".join(
        str(part)
        for part in (
            article.get("prompt", ""),
            article.get("headline", ""),
            article.get("dek", ""),
            article.get("summary", ""),
            " ".join(str(t) for t in terms) if isinstance(terms, list) else str(terms),
        )
        if part
    ).lower()
    text = f" {text} "
    best_section = DEFAULT_ARTICLE_SECTION
    best_score = 0
    for section, keywords in _SECTION_KEYWORDS.items():
        score = sum(text.count(keyword.lower()) for keyword in keywords)
        if score > best_score:
            best_section = section
            best_score = score
    return best_section


def _list_generated_articles_by_section_cur(cur: Any, section: str, limit: int = 20) -> list[dict[str, Any]]:
    """
    Return the latest generated articles for a topic, newest first.
    Prefers the stored section assignment; legacy rows without one are
    matched by section keywords so nothing disappears from topic pages.
    """
    slug = section.lower()
    if slug == "sporks":
        slug = "sports"
    keywords = _SECTION_KEYWORDS.get(slug, [])
    if not keywords:
        return list_generated_articles(limit=limit)
    keyword_conditions = " OR ".join(["prompt ILIKE %s OR headline ILIKE %s"] * len(keywords))
    keyword_params = [val for kw in keywords for val in (f"%{kw}%", f"%{kw}%")]
    if slug == "sports":
        section_match = "section IN ('sports', 'sporks')"
        section_params: list[Any] = []
    else:
        section_match = "section = %s"
        section_params = [slug]
    cur.execute(
        f"""
        SELECT {_GENERATED_FEED_COLUMNS}
        FROM generated_articles
        WHERE created_at > NOW() - INTERVAL '14 days'
          AND (
            {section_match}
            OR (COALESCE(section, '') = '' AND ({keyword_conditions}))
          )
        ORDER BY
          (
            source_count * 0.55
            + accuracy_score * 0.035
            + fairness_score * 0.02
          ) / POWER(EXTRACT(EPOCH FROM (NOW() - created_at)) / 3600.0 + 2.0, 0.34) DESC,
          created_at DESC
        LIMIT %s
        """,
        [*section_params, *keyword_params, max(limit * 3, limit)],
    )
    items = [_decode_feed_article(row) for row in cur.fetchall()]
    return _filter_feed_articles(items, limit)


def list_generated_articles_by_section(section: str, limit: int = 20) -> list[dict[str, Any]]:
    slug = section.lower()
    if slug == "sporks":
        slug = "sports"
    keywords = _SECTION_KEYWORDS.get(slug, [])
    if not keywords:
        return list_generated_articles(limit=limit)
    with get_connection() as conn:
        with conn.cursor() as cur:
            return _list_generated_articles_by_section_cur(cur, slug, limit)


def generated_prompt_exists_recent(prompt: str, max_age_minutes: int = 45) -> bool:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM generated_articles
                WHERE lower(prompt) = lower(%s)
                  AND created_at > NOW() - (%s::text || ' minutes')::interval
                LIMIT 1
                """,
                (prompt, max(1, max_age_minutes)),
            )
            return bool(cur.fetchone())


def list_section_generation_prompts(section: str, limit: int = 9) -> list[str]:
    slug = section.lower()
    if slug == "sporks":
        slug = "sports"
    keywords = _SECTION_KEYWORDS.get(slug, [])
    if not keywords:
        return []
    cluster_conditions = " OR ".join(["sc.topic_label ILIKE %s"] * len(keywords))
    article_conditions = " OR ".join(
        ["a.title ILIKE %s OR a.description ILIKE %s OR a.raw_text ILIKE %s"] * len(keywords)
    )
    cluster_params = [f"%{kw}%" for kw in keywords]
    article_params = [val for kw in keywords for val in (f"%{kw}%", f"%{kw}%", f"%{kw}%")]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH candidates AS (
                  SELECT
                    sc.topic_label AS prompt,
                    sc.updated_at AS observed_at,
                    COUNT(DISTINCT sca.article_id) AS source_count,
                    2 AS source_priority
                  FROM story_clusters sc
                  LEFT JOIN story_cluster_articles sca ON sca.story_cluster_id = sc.id
                  WHERE sc.updated_at > NOW() - INTERVAL '48 hours'
                    AND ({cluster_conditions})
                  GROUP BY sc.id, sc.topic_label, sc.updated_at
                  UNION ALL
                  SELECT
                    a.title AS prompt,
                    a.created_at AS observed_at,
                    1 AS source_count,
                    1 AS source_priority
                  FROM articles a
                  WHERE a.created_at > NOW() - INTERVAL '48 hours'
                    AND ({article_conditions})
                )
                SELECT prompt
                FROM candidates
                WHERE prompt IS NOT NULL AND length(prompt) > 12
                ORDER BY
                  (source_count * 1.25 + source_priority)
                  / POWER(EXTRACT(EPOCH FROM (NOW() - observed_at)) / 3600.0 + 2.0, 0.28) DESC,
                  observed_at DESC
                LIMIT %s
                """,
                [*cluster_params, *article_params, max(limit, 1)],
            )
            prompts: list[str] = []
            seen: set[str] = set()
            for row in cur.fetchall():
                prompt = str(row.get("prompt") or "").strip()
                key = " ".join(prompt.lower().split())
                if not key or key in seen:
                    continue
                seen.add(key)
                prompts.append(prompt)
            return prompts


def list_stories_by_section(section: str, limit: int = 20) -> list[dict[str, Any]]:
    slug = section.lower()
    if slug == "sporks":
        slug = "sports"
    keywords = _SECTION_KEYWORDS.get(slug, [])
    if not keywords:
        return list_stories()[:limit]
    conditions = " OR ".join(["topic_label ILIKE %s"] * len(keywords))
    params = [f"%{kw}%" for kw in keywords] + [limit]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  sc.id, sc.topic_label, sc.created_at, sc.updated_at,
                  COUNT(DISTINCT sca.article_id) AS article_count,
                  COALESCE((
                    SELECT gs.summary_text FROM generated_summaries gs
                    WHERE gs.story_cluster_id = sc.id
                    ORDER BY gs.created_at DESC, gs.id DESC LIMIT 1
                  ), '') AS summary_text
                FROM story_clusters sc
                LEFT JOIN story_cluster_articles sca ON sca.story_cluster_id = sc.id
                WHERE {conditions}
                GROUP BY sc.id
                ORDER BY sc.updated_at DESC
                LIMIT %s
                """,
                params,
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def record_history(
    user_id: int | None,
    session_id: str | None,
    action_type: str,
    topic: str | None = None,
    section: str | None = None,
    prompt: str | None = None,
    article_id: str | None = None,
) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_history (user_id, session_id, action_type, topic, section, prompt, article_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, session_id, action_type, topic, section, prompt, article_id),
            )
            if article_id and action_type in {"view", "read"}:
                cur.execute("SELECT owner_user_id, headline FROM generated_articles WHERE id = %s", (article_id,))
                article = cur.fetchone()
                _create_notification(
                    cur,
                    article.get("owner_user_id") if article else None,
                    "article_read",
                    f"Your article got a new read: {article.get('headline', 'Signal article') if article else 'Signal article'}",
                    article_id=article_id,
                    actor_user_id=user_id,
                    actor_name="Reader",
                )


def get_auto_preferences(user_id: int | None, session_id: str | None = None) -> dict[str, Any]:
    """Derive preferred sections and topics from a user's history."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id:
                cur.execute(
                    """
                    SELECT section, COUNT(*) AS cnt FROM user_history
                    WHERE user_id = %s AND section IS NOT NULL
                    GROUP BY section ORDER BY cnt DESC LIMIT 5
                    """,
                    (user_id,),
                )
            elif session_id:
                cur.execute(
                    """
                    SELECT section, COUNT(*) AS cnt FROM user_history
                    WHERE session_id = %s AND section IS NOT NULL
                    GROUP BY section ORDER BY cnt DESC LIMIT 5
                    """,
                    (session_id,),
                )
            else:
                return {"preferred_sections": [], "preferred_topics": [], "source_threshold": 8}
            top_sections = [row["section"] for row in cur.fetchall()]

            if user_id:
                cur.execute(
                    """
                    SELECT prompt FROM user_history
                    WHERE user_id = %s AND prompt IS NOT NULL
                    ORDER BY created_at DESC LIMIT 40
                    """,
                    (user_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT prompt FROM user_history
                    WHERE session_id = %s AND prompt IS NOT NULL
                    ORDER BY created_at DESC LIMIT 40
                    """,
                    (session_id,),
                )
            prompts = [row["prompt"] for row in cur.fetchall()]
    word_counts: dict[str, int] = {}
    stop = {"the", "and", "for", "from", "with", "that", "this", "are", "was", "have", "been", "more", "will"}
    for p in prompts:
        for word in str(p).lower().split():
            word = word.strip(".,;:!?()[]")
            if len(word) >= 4 and word not in stop:
                word_counts[word] = word_counts.get(word, 0) + 1
    top_topics = sorted(word_counts, key=lambda w: word_counts[w], reverse=True)[:8]
    return {
        "preferred_sections": top_sections,
        "preferred_topics": top_topics,
        "source_threshold": 8,
    }


def list_saved_stories(user_id: int | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            if user_id is None:
                cur.execute("SELECT * FROM saved_stories ORDER BY saved_at DESC")
            else:
                cur.execute(
                    "SELECT * FROM saved_stories WHERE user_id = %s ORDER BY saved_at DESC",
                    (user_id,),
                )
            return [row_to_dict(row) for row in cur.fetchall()]


def _create_notification(
    cur: Any,
    user_id: int | None,
    notification_type: str,
    message: str,
    article_id: str | None = None,
    comment_id: int | None = None,
    actor_user_id: int | None = None,
    actor_name: str = "Reader",
) -> None:
    if not user_id or user_id == actor_user_id:
        return
    cur.execute(
        """
        INSERT INTO notifications
        (user_id, type, article_id, comment_id, actor_user_id, actor_name, message)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (user_id, notification_type, article_id, comment_id, actor_user_id, actor_name, message),
    )


def like_article(article_id: str, user_id: int | None, session_id: str | None = "", actor_name: str = "Reader") -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT owner_user_id, headline FROM generated_articles WHERE id = %s", (article_id,))
            article = cur.fetchone()
            if not article:
                return {"ok": False, "liked": False, "likeCount": 0}
            if user_id:
                cur.execute(
                    "INSERT INTO article_likes (article_id, user_id, session_id) VALUES (%s, %s, NULL) ON CONFLICT(article_id, user_id) DO NOTHING",
                    (article_id, user_id),
                )
            else:
                cur.execute(
                    "INSERT INTO article_likes (article_id, session_id) VALUES (%s, %s) ON CONFLICT(article_id, session_id) DO NOTHING",
                    (article_id, session_id or ""),
                )
            _create_notification(
                cur,
                article.get("owner_user_id"),
                "article_like",
                f"{actor_name} liked your article: {article.get('headline', 'Signal article')}",
                article_id=article_id,
                actor_user_id=user_id,
                actor_name=actor_name,
            )
            cur.execute("SELECT COUNT(*) AS count FROM article_likes WHERE article_id = %s", (article_id,))
            return {"ok": True, "liked": True, "likeCount": int(cur.fetchone()["count"])}


def add_article_comment(
    article_id: str,
    body: str,
    user_id: int | None,
    session_id: str | None = "",
    author_name: str = "Reader",
    parent_comment_id: int | None = None,
) -> dict[str, Any]:
    clean_body = body.strip()[:1200]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT owner_user_id, headline FROM generated_articles WHERE id = %s", (article_id,))
            article = cur.fetchone()
            if not article or not clean_body:
                return {"ok": False}
            cur.execute(
                """
                INSERT INTO article_comments
                (article_id, user_id, session_id, author_name, body, parent_comment_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (article_id, user_id, session_id or "", author_name or "Reader", clean_body, parent_comment_id),
            )
            comment = row_to_dict(cur.fetchone())
            _create_notification(
                cur,
                article.get("owner_user_id"),
                "article_comment",
                f"{author_name or 'Reader'} commented on your article: {article.get('headline', 'Signal article')}",
                article_id=article_id,
                comment_id=int(comment["id"]),
                actor_user_id=user_id,
                actor_name=author_name or "Reader",
            )
            if parent_comment_id:
                cur.execute("SELECT user_id FROM article_comments WHERE id = %s", (parent_comment_id,))
                parent = cur.fetchone()
                _create_notification(
                    cur,
                    parent.get("user_id") if parent else None,
                    "comment_reply",
                    f"{author_name or 'Reader'} replied to your comment.",
                    article_id=article_id,
                    comment_id=int(comment["id"]),
                    actor_user_id=user_id,
                    actor_name=author_name or "Reader",
                )
            return {"ok": True, "comment": comment}


def like_comment(comment_id: int, user_id: int | None, session_id: str | None = "", actor_name: str = "Reader") -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, article_id FROM article_comments WHERE id = %s", (comment_id,))
            comment = cur.fetchone()
            if not comment:
                return {"ok": False, "liked": False, "likeCount": 0}
            if user_id:
                cur.execute(
                    "INSERT INTO comment_likes (comment_id, user_id, session_id) VALUES (%s, %s, NULL) ON CONFLICT(comment_id, user_id) DO NOTHING",
                    (comment_id, user_id),
                )
            else:
                cur.execute(
                    "INSERT INTO comment_likes (comment_id, session_id) VALUES (%s, %s) ON CONFLICT(comment_id, session_id) DO NOTHING",
                    (comment_id, session_id or ""),
                )
            _create_notification(
                cur,
                comment.get("user_id"),
                "comment_like",
                f"{actor_name or 'Reader'} liked your comment.",
                article_id=comment.get("article_id"),
                comment_id=comment_id,
                actor_user_id=user_id,
                actor_name=actor_name or "Reader",
            )
            cur.execute("SELECT COUNT(*) AS count FROM comment_likes WHERE comment_id = %s", (comment_id,))
            return {"ok": True, "liked": True, "likeCount": int(cur.fetchone()["count"])}


def get_article_social(article_id: str, user_id: int | None = None, session_id: str | None = "") -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS count FROM article_likes WHERE article_id = %s", (article_id,))
            like_count = int(cur.fetchone()["count"])
            if user_id:
                cur.execute("SELECT 1 FROM article_likes WHERE article_id = %s AND user_id = %s", (article_id, user_id))
            else:
                cur.execute("SELECT 1 FROM article_likes WHERE article_id = %s AND session_id = %s", (article_id, session_id or ""))
            liked = bool(cur.fetchone())
            cur.execute(
                """
                SELECT c.*,
                  COALESCE((SELECT COUNT(*) FROM comment_likes cl WHERE cl.comment_id = c.id), 0) AS like_count
                FROM article_comments c
                WHERE c.article_id = %s
                ORDER BY c.created_at ASC
                LIMIT 80
                """,
                (article_id,),
            )
            comments = [row_to_dict(row) for row in cur.fetchall()]
    return {"articleId": article_id, "likeCount": like_count, "liked": liked, "comments": comments}


def list_notifications(user_id: int, limit: int = 30) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM notifications
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            return [row_to_dict(row) for row in cur.fetchall()]


def mark_notifications_read(user_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE notifications SET is_read = 1 WHERE user_id = %s", (user_id,))


def list_trending_generated_articles(limit: int = 18) -> list[dict[str, Any]]:
    """
    Trending ranking based on: views, time (recency decay), likes, comments,
    and relevance. Relevance combines source depth (independent source count)
    with the pipeline's verification and balance estimates.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH metrics AS (
                  SELECT
                    ga.id, ga.source, ga.tag, ga.trend_url, ga.prompt, ga.headline, ga.dek, ga.summary,
                    ga.sources, ga.source_count, ga.denied_for_bias, ga.fairness_score, ga.accuracy_score,
                    ga.generation_mode, ga.used_live_sources, ga.fallback_reason, ga.status, ga.created_at,
                    COUNT(DISTINCT uh.id) FILTER (WHERE uh.action_type IN ('view', 'read')) AS views,
                    COUNT(DISTINCT ss.id) AS saves,
                    COUNT(DISTINCT al.id) AS likes,
                    COUNT(DISTINCT ac.id) AS comments,
                    (ga.source_count * 0.5 + ga.accuracy_score * 0.05 + ga.fairness_score * 0.03) AS relevance,
                    EXTRACT(EPOCH FROM (NOW() - ga.created_at)) / 3600.0 AS age_hours
                  FROM generated_articles ga
                  LEFT JOIN user_history uh ON uh.article_id = ga.id
                  LEFT JOIN saved_stories ss ON ss.story_id = ga.id
                  LEFT JOIN article_likes al ON al.article_id = ga.id
                  LEFT JOIN article_comments ac ON ac.article_id = ga.id
                  WHERE ga.created_at > NOW() - INTERVAL '14 days'
                  GROUP BY ga.id
                ),
                ranked AS (
                  SELECT *,
                    (views * 3.0 + likes * 5.0 + comments * 6.0 + relevance)
                    / POWER(age_hours + 2.0, 0.72) AS trend_score,
                    ROW_NUMBER() OVER (
                      ORDER BY
                      (views * 3.0 + likes * 5.0 + comments * 6.0 + relevance)
                      / POWER(age_hours + 2.0, 0.72) DESC
                    ) AS current_rank,
                    ROW_NUMBER() OVER (
                      ORDER BY
                      (views * 3.0 + likes * 5.0 + comments * 6.0 + relevance)
                      / POWER(GREATEST(age_hours - 24.0, 2.0) + 2.0, 0.72) DESC
                    ) AS previous_rank
                  FROM metrics
                )
                SELECT * FROM ranked
                ORDER BY current_rank
                LIMIT %s
                """,
                (max(limit * 3, limit),),
            )
            items: list[dict[str, Any]] = []
            for row in cur.fetchall():
                trend_metrics = {
                    "views": int(row.get("views") or 0),
                    "saves": int(row.get("saves") or 0),
                    "likes": int(row.get("likes") or 0),
                    "comments": int(row.get("comments") or 0),
                    "score": round(float(row.get("trend_score") or 0), 3),
                    "currentRank": int(row.get("current_rank") or 0),
                    "previousRank": int(row.get("previous_rank") or 0),
                }
                decoded = _decode_feed_article(row, trend_metrics=trend_metrics)
                if article_is_blocked(decoded).blocked:
                    continue
                items.append(decoded)
            return items[:limit]


def list_trending_topics(limit: int = 12) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            return _fetch_trending_topics(cur, limit)


def _fetch_trending_topics(cur: Any, limit: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT entity_text, entity_type, COUNT(*) AS mentions
        FROM entities
        WHERE created_at > NOW() - INTERVAL '72 hours'
          AND LENGTH(entity_text) > 2
        GROUP BY entity_text, entity_type
        HAVING COUNT(*) >= 2
        ORDER BY mentions DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    if rows:
        return [row_to_dict(r) for r in rows]

    cur.execute(
        """
        SELECT entity_text, entity_type, COUNT(*) AS mentions
        FROM entities
        WHERE created_at > NOW() - INTERVAL '72 hours'
          AND LENGTH(entity_text) > 3
        GROUP BY entity_text, entity_type
        ORDER BY mentions DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    if rows:
        return [row_to_dict(r) for r in rows]

    cur.execute(
        """
        SELECT sc.topic_label AS entity_text,
               'topic'::text  AS entity_type,
               COUNT(sca.article_id) AS mentions
        FROM story_clusters sc
        JOIN story_cluster_articles sca ON sca.story_cluster_id = sc.id
        GROUP BY sc.id, sc.topic_label
        ORDER BY mentions DESC
        LIMIT %s
        """,
        (limit,),
    )
    rows = cur.fetchall()
    if rows:
        return [row_to_dict(r) for r in rows]

    cur.execute(
        """
        SELECT title AS entity_text,
               source_name AS entity_type,
               1 AS mentions
        FROM articles
        WHERE status = 'processed'
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [row_to_dict(r) for r in cur.fetchall()]


def bootstrap_feeds(
    *,
    latest_limit: int = 25,
    story_limit: int = 20,
    trending_limit: int = 18,
    section_limit: int = 18,
    topics_limit: int = 10,
) -> dict[str, Any]:
    """
    Load every reader-facing feed in a single database connection so cold starts
    pay one round-trip instead of nine.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_GENERATED_FEED_COLUMNS}
                FROM generated_articles
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (max(latest_limit * 3, latest_limit),),
            )
            latest = _filter_feed_articles(
                [_decode_feed_article(row) for row in cur.fetchall()],
                latest_limit,
            )

            cur.execute(
                """
                SELECT
                  sc.id,
                  sc.topic_label,
                  sc.created_at,
                  sc.updated_at,
                  COUNT(DISTINCT sca.article_id) AS article_count,
                  COALESCE((
                    SELECT gs.summary_text
                    FROM generated_summaries gs
                    WHERE gs.story_cluster_id = sc.id
                    ORDER BY gs.created_at DESC, gs.id DESC
                    LIMIT 1
                  ), '') AS summary_text
                FROM story_clusters sc
                LEFT JOIN story_cluster_articles sca ON sca.story_cluster_id = sc.id
                GROUP BY sc.id
                ORDER BY sc.updated_at DESC
                LIMIT %s
                """,
                (story_limit,),
            )
            stories = [row_to_dict(row) for row in cur.fetchall()]

            cur.execute(
                f"""
                WITH metrics AS (
                  SELECT
                    ga.id, ga.source, ga.tag, ga.trend_url, ga.prompt, ga.headline, ga.dek, ga.summary,
                    ga.sources, ga.source_count, ga.denied_for_bias, ga.fairness_score, ga.accuracy_score,
                    ga.generation_mode, ga.used_live_sources, ga.fallback_reason, ga.status, ga.created_at,
                    COUNT(DISTINCT uh.id) FILTER (WHERE uh.action_type IN ('view', 'read')) AS views,
                    COUNT(DISTINCT ss.id) AS saves,
                    COUNT(DISTINCT al.id) AS likes,
                    COUNT(DISTINCT ac.id) AS comments,
                    EXTRACT(EPOCH FROM (NOW() - ga.created_at)) / 3600.0 AS age_hours
                  FROM generated_articles ga
                  LEFT JOIN user_history uh ON uh.article_id = ga.id
                  LEFT JOIN saved_stories ss ON ss.story_id = ga.id
                  LEFT JOIN article_likes al ON al.article_id = ga.id
                  LEFT JOIN article_comments ac ON ac.article_id = ga.id
                  WHERE ga.created_at > NOW() - INTERVAL '14 days'
                  GROUP BY ga.id
                ),
                ranked AS (
                  SELECT *,
                    (views * 3.0 + saves * 8.0 + likes * 5.0 + comments * 6.0 + source_count * 0.35)
                    / POWER(age_hours + 2.0, 0.72) AS trend_score,
                    ROW_NUMBER() OVER (
                      ORDER BY
                      (views * 3.0 + saves * 8.0 + likes * 5.0 + comments * 6.0 + source_count * 0.35)
                      / POWER(age_hours + 2.0, 0.72) DESC
                    ) AS current_rank,
                    ROW_NUMBER() OVER (
                      ORDER BY
                      (views * 3.0 + saves * 8.0 + likes * 5.0 + comments * 6.0 + source_count * 0.35)
                      / POWER(GREATEST(age_hours - 24.0, 2.0) + 2.0, 0.72) DESC
                    ) AS previous_rank
                  FROM metrics
                )
                SELECT * FROM ranked
                ORDER BY current_rank
                LIMIT %s
                """,
                (max(trending_limit * 3, trending_limit),),
            )
            trending: list[dict[str, Any]] = []
            for row in cur.fetchall():
                trend_metrics = {
                    "views": int(row.get("views") or 0),
                    "saves": int(row.get("saves") or 0),
                    "likes": int(row.get("likes") or 0),
                    "comments": int(row.get("comments") or 0),
                    "score": round(float(row.get("trend_score") or 0), 3),
                    "currentRank": int(row.get("current_rank") or 0),
                    "previousRank": int(row.get("previous_rank") or 0),
                }
                decoded = _decode_feed_article(row, trend_metrics=trend_metrics)
                if article_is_blocked(decoded).blocked:
                    continue
                trending.append(decoded)
                if len(trending) >= trending_limit:
                    break

            sections: dict[str, list[dict[str, Any]]] = {}
            for slug in FEED_SECTION_SLUGS:
                sections[slug] = _list_generated_articles_by_section_cur(cur, slug, section_limit)

            topics = _fetch_trending_topics(cur, topics_limit)

    return {
        "latest": latest,
        "stories": stories,
        "trending": trending,
        "sections": sections,
        "trendingTopics": topics,
    }
