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


def list_stories() -> list[dict[str, Any]]:
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
                """
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


def search(q: str) -> list[dict[str, Any]]:
    term = f"%{q}%"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source_name, title, url, published_at, clean_text
                FROM articles
                WHERE title ILIKE %s OR clean_text ILIKE %s
                ORDER BY published_at DESC
                LIMIT 25
                """,
                (term, term),
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
    with get_connection() as conn:
        with conn.cursor() as cur:
            _ensure_generated_article_metadata_columns(cur)
            cur.execute(
                """
                INSERT INTO generated_articles
                (id, owner_user_id, source, tag, trend_url, prompt, headline, dek, summary, body, facts,
                 terms, sources, source_links, consensus, source_count, denied_for_bias,
                 fairness_score, accuracy_score, score_metadata, generation_mode, source_quality,
                 consensus_level, used_live_sources, fallback_reason, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    article.get("status", "published"),
                    article.get("createdAt"),
                ),
            )
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
    return {
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
        "status": item["status"],
        "createdAt": item["created_at"],
    }


def list_generated_articles(limit: int = 25) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM generated_articles ORDER BY created_at DESC LIMIT %s",
                (max(limit * 3, limit),),
            )
            items = [_decode_generated_article(row) for row in cur.fetchall()]
            return [item for item in items if not article_is_blocked(item).blocked][:limit]


def get_generated_article(article_id: str) -> dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM generated_articles WHERE id = %s", (article_id,))
            article = _decode_generated_article(cur.fetchone())
            return {} if article and article_is_blocked(article).blocked else article


def delete_generated_article(article_id: str) -> int:
    with get_connection() as conn:
        with conn.cursor() as cur:
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
                    cur.execute("DELETE FROM saved_stories WHERE story_id = %s", (article_id,))
                    cur.execute("DELETE FROM user_history WHERE article_id = %s", (article_id,))
                    cur.execute("DELETE FROM generated_articles WHERE id = %s", (article_id,))
                    deleted.append(article_id)
    return {"scanned": scanned, "deleted": len(deleted), "articleIds": deleted}


def upsert_user(name: str, email: str, plan: str = "Reader", supabase_user_id: str | None = None) -> dict[str, Any]:
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
                          supabase_user_id = %s
                      WHERE email = %s OR supabase_user_id = %s
                      RETURNING *
                    ),
                    inserted AS (
                      INSERT INTO users (name, email, plan, supabase_user_id)
                      SELECT %s, %s, %s, %s
                      WHERE NOT EXISTS (SELECT 1 FROM updated)
                      ON CONFLICT(email) DO UPDATE SET
                        name = EXCLUDED.name,
                        plan = EXCLUDED.plan,
                        supabase_user_id = EXCLUDED.supabase_user_id
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
                        supabase_user_id,
                        email,
                        supabase_user_id,
                        name,
                        email,
                        plan,
                        supabase_user_id,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO users (name, email, plan)
                    VALUES (%s, %s, %s)
                    ON CONFLICT(email) DO UPDATE SET name = EXCLUDED.name, plan = EXCLUDED.plan
                    RETURNING *
                    """,
                    (name, email, plan),
                )
            return row_to_dict(cur.fetchone())


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
    "markets": ["market", "economy", "financial", "inflation", "trade", "bank", "gdp", "stock", "fed ", "interest rate"],
    "technology": ["technology", "artificial intelligence", " ai ", "semiconductor", "chip", "cybersecurity", "tech", "software", "digital"],
    "climate": ["climate", "weather", "flood", "hurricane", "renewable", "carbon", "environment", "energy", "wildfire"],
}


def list_generated_articles_by_section(section: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return generated articles whose prompt matches the given section's keywords."""
    keywords = _SECTION_KEYWORDS.get(section.lower(), [])
    if not keywords:
        return list_generated_articles(limit=limit)
    conditions = " OR ".join(["prompt ILIKE %s OR headline ILIKE %s"] * len(keywords))
    params = [val for kw in keywords for val in (f"%{kw}%", f"%{kw}%")] + [limit]
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT * FROM generated_articles
                WHERE {conditions}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params[:-1] + [max(limit * 3, limit)],
            )
            items = [_decode_generated_article(row) for row in cur.fetchall()]
            return [item for item in items if not article_is_blocked(item).blocked][:limit]


def list_stories_by_section(section: str, limit: int = 20) -> list[dict[str, Any]]:
    keywords = _SECTION_KEYWORDS.get(section.lower(), [])
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
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH metrics AS (
                  SELECT
                    ga.*,
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
                (max(limit * 3, limit),),
            )
            items: list[dict[str, Any]] = []
            for row in cur.fetchall():
                decoded = _decode_generated_article(row)
                if article_is_blocked(decoded).blocked:
                    continue
                decoded["trendMetrics"] = {
                    "views": int(row.get("views") or 0),
                    "saves": int(row.get("saves") or 0),
                    "likes": int(row.get("likes") or 0),
                    "comments": int(row.get("comments") or 0),
                    "score": round(float(row.get("trend_score") or 0), 3),
                    "currentRank": int(row.get("current_rank") or 0),
                    "previousRank": int(row.get("previous_rank") or 0),
                }
                items.append(decoded)
            return items[:limit]
