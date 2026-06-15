from __future__ import annotations

import re

import numpy as np

from app.ingest.source_registry import domain_from_url


# ── Jaccard fallback (used if the embedding model is unavailable) ─────────────

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "by",
    "for", "that", "with", "as", "from",
}

_ALIASES = {
    "approved": "passed", "clears": "passed",
    "legislation": "bill", "proposal": "bill",
    "defeated": "lost", "wins": "won", "beats": "beat",
    "says": "said", "tells": "said", "announces": "announced",
}


def _claim_terms(claim: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", claim.lower())
    return frozenset(_ALIASES.get(w, w) for w in words if w not in STOPWORDS)


def _jaccard_similar(left: str, right: str) -> bool:
    lt, rt = _claim_terms(left), _claim_terms(right)
    if not lt or not rt:
        return False
    shared = lt & rt
    union = lt | rt
    j = len(shared) / len(union)
    left_nums = set(re.findall(r"\d+(?:\.\d+)?%?", left))
    right_nums = set(re.findall(r"\d+(?:\.\d+)?%?", right))
    numeric_overlap = bool(left_nums & right_nums)
    if numeric_overlap and len(shared) >= 2 and j >= 0.22:
        return True
    if len(shared) >= 4 and j >= 0.28:
        return True
    if len(shared) >= 3 and j >= 0.35:
        return True
    if len(shared) >= 2 and j >= 0.50:
        return True
    return False


def _source_domain(item: dict) -> str:
    return str(item.get("source_domain") or domain_from_url(str(item.get("url", ""))) or item.get("source_name", "")).lower()


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\b\d+(?:[.,]\d+)?%?\b|\b\d+\s*-\s*\d+\b", text))


def _is_conflicting_group(items: list[dict]) -> bool:
    numeric_sets = [_numbers(str(item.get("claim_text", ""))) for item in items]
    numeric_sets = [nums for nums in numeric_sets if nums]
    if len(numeric_sets) >= 2 and len({tuple(sorted(nums)) for nums in numeric_sets}) > 1:
        return True
    texts = [str(item.get("claim_text", "")).lower() for item in items]
    opposites = (("increased", "decreased"), ("rose", "fell"), ("approved", "rejected"), ("won", "lost"))
    return any(any(left in text for text in texts) and any(right in text for text in texts) for left, right in opposites)


# ── Semantic clustering ────────────────────────────────────────────────────────

# Threshold: cosine similarity ≥ 0.72 → same claim from different sources.
# Paraphrases of the same fact typically score 0.78–0.95.
# Genuinely different claims typically score 0.10–0.55.
_SIM_THRESHOLD = 0.72


def _semantic_groups(texts: list[str]) -> list[list[int]]:
    """
    Cluster claim texts by semantic similarity using sentence embeddings.
    Returns a list of groups, each group being a list of text indices.
    Uses a greedy O(N²) algorithm: for each unassigned claim, find all
    unassigned claims with cosine similarity ≥ threshold and put them
    in the same group.
    """
    from app.llm.embeddings import get_embeddings, cosine_similarity_matrix

    embeddings = get_embeddings(texts)          # (N, D) — already L2-normalised
    sim = cosine_similarity_matrix(embeddings)  # (N, N) cosine similarities
    np.fill_diagonal(sim, 0.0)                  # ignore self-similarity

    assigned = [False] * len(texts)
    groups: list[list[int]] = []

    for i in range(len(texts)):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, len(texts)):
            if not assigned[j] and sim[i][j] >= _SIM_THRESHOLD:
                group.append(j)
                assigned[j] = True
        groups.append(group)

    return groups


def _jaccard_groups(texts: list[str]) -> list[list[int]]:
    """Fallback grouper using Jaccard word overlap."""
    groups: list[list[int]] = []
    assigned = [False] * len(texts)

    for i in range(len(texts)):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, len(texts)):
            if not assigned[j] and _jaccard_similar(texts[i], texts[j]):
                group.append(j)
                assigned[j] = True
        groups.append(group)

    return groups


# ── Public API ─────────────────────────────────────────────────────────────────

def detect_consensus(cluster_claims: list[dict], *, use_semantic: bool = True) -> list[dict]:
    """
    Group claims by semantic similarity (sentence-transformers), falling back
    to Jaccard word overlap if the model is unavailable.

    A group containing claims from ≥ 2 distinct source outlets is marked
    "supported" — meaning multiple independent sources report the same fact.
    Single-source claims are marked "unique" (or "uncertain" if low-confidence).
    """
    if not cluster_claims:
        return []

    texts = [str(c["claim_text"]) for c in cluster_claims]

    # Try semantic grouping first; fall back to Jaccard on any error
    try:
        if not use_semantic:
            raise RuntimeError("semantic disabled")
        groups = _semantic_groups(texts)
        method = "semantic"
    except Exception:
        groups = _jaccard_groups(texts)
        method = "jaccard"

    consensus: list[dict] = []
    for group_indices in groups:
        items = [cluster_claims[i] for i in group_indices]
        sources = sorted({str(item["source_name"]) for item in items})
        domains = sorted({_source_domain(item) for item in items if _source_domain(item)})
        support_count = len(domains or sources)

        if support_count >= 2 and _is_conflicting_group(items):
            status = "conflicting"
        elif support_count >= 2:
            status = "supported"
        elif any(float(item.get("confidence_score", 0)) < 0.7 for item in items):
            status = "uncertain"
        else:
            status = "unique"

        avg_confidence = sum(float(item.get("confidence_score", 0.75)) for item in items) / len(items)
        boosted = min(0.98, avg_confidence + 0.05 * max(0, support_count - 1))

        consensus.append({
            "claim_text": str(items[0]["claim_text"]),
            "support_count": support_count,
            "sources": sources,
            "source_domains": domains,
            "status": status,
            "source_diversity_score": round(min(1.0, support_count / 4), 3),
            "confidence_score": round(boosted, 3),
            "method": method,
        })

    return sorted(
        consensus,
        key=lambda c: (c["status"] != "supported", -c["support_count"], -c["confidence_score"]),
    )
