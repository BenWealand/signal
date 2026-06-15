from __future__ import annotations

from app.clustering.story_clusterer import cluster_articles
from app.db import queries
from app.llm.claim_extractor import extract_claims
from app.llm.consensus import detect_consensus
from app.llm.summarizer import generate_summary
from app.nlp.ner import extract_entities
from app.processing.clean_text import clean_article_text


def run_pipeline() -> list[dict[str, object]]:
    articles = queries.list_articles_needing_processing()
    for article in articles:
        if article.get("duplicate_of"):
            queries.update_article_processing(int(article["id"]), article.get("clean_text") or "", "duplicate")
            continue
        clean_text = clean_article_text(article["raw_text"])
        entities = extract_entities(clean_text)
        entity_names = [entity["text"] for entity in entities]
        claims = extract_claims(clean_text, entities=entity_names)
        queries.update_article_processing(int(article["id"]), clean_text, "processed")
        queries.replace_entities(int(article["id"]), entities)
        queries.replace_claims(int(article["id"]), claims)

    processed_articles = queries.list_articles(status="processed")
    cluster_map = cluster_articles(processed_articles)
    results = []
    for topic_label, article_ids in cluster_map.items():
        cluster_id = queries.create_cluster(topic_label, article_ids)
        cluster_claims = queries.get_cluster_claims(cluster_id)
        consensus = detect_consensus(cluster_claims)
        queries.replace_consensus_claims(cluster_id, consensus)
        summary = generate_summary(consensus)
        queries.save_summary(cluster_id, summary)
        results.append(
            {
                "story_cluster_id": cluster_id,
                "topic_label": topic_label,
                "summary": summary,
                "supported_claims": [claim for claim in consensus if claim["status"] == "supported"],
                "sources": sorted({source for claim in consensus for source in claim["sources"]}),
            }
        )
    return results
