from __future__ import annotations

import re


OPINION_MARKERS = {
    "should",
    "could",
    "might",
    "may",
    "believes",
    "believe",
    "critics say",
    "supporters say",
    "likely",
    "expected to",
    "forecast",
    "predict",
    "prediction",
    "opinion",
}

ATTRIBUTION_PATTERNS = (
    r"\baccording to\b",
    r"\bsaid\b",
    r"\btold\b",
    r"\breported\b",
    r"\bannounced\b",
    r"\bconfirmed\b",
    r"\bcited\b",
)

BOILERPLATE_MARKERS = {
    "subscribe", "newsletter", "cookie", "privacy policy", "advertisement",
    "all rights reserved", "sign up", "follow us", "read more",
}


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    protected = {
        "U.S.": "US_PLACEHOLDER",
        "Mr.": "MR_PLACEHOLDER",
        "Ms.": "MS_PLACEHOLDER",
        "Dr.": "DR_PLACEHOLDER",
    }
    for source, token in protected.items():
        text = text.replace(source, token)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text)
    sentences = []
    for part in parts:
        for source, token in protected.items():
            part = part.replace(token, source)
        sentences.append(part.strip())
    return sentences


def _claim_type(sentence: str) -> str:
    lowered = sentence.lower()
    if re.search(r"\baccording to\b|\bsaid\b|\btold\b|\breported\b|\bannounced\b|\bconfirmed\b", lowered):
        return "quote" if re.search(r"[\"“”]", sentence) else "attributed"
    if re.search(r"\b\d+(?:[.,]\d+)?%?\b|\b\d+\s*-\s*\d+\b", sentence):
        return "number"
    return "event"


def _is_candidate_sentence(sentence: str) -> bool:
    if len(sentence) < 35 or len(sentence) > 360:
        return False
    lowered = sentence.lower()
    if any(marker in lowered for marker in BOILERPLATE_MARKERS):
        return False
    if any(marker in lowered for marker in OPINION_MARKERS):
        return False
    if sentence.count(",") > 8:
        return False
    has_fact_signal = bool(
        re.search(r"\b\d+(?:[.,]\d+)?%?\b|\bpassed\b|\bapproved\b|\breported\b|\bsaid\b|\bannounced\b|\bconfirmed\b|\breleased\b|\bfiled\b|\bwon\b|\blost\b", lowered)
        or re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", sentence)
    )
    return has_fact_signal


def _match_entities(sentence: str, entities: list[str]) -> list[str]:
    lowered = sentence.lower()
    matched = [entity for entity in entities if entity and entity.lower() in lowered]
    inferred = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b", sentence)
    for entity in inferred:
        if entity.lower() not in {"The", "This", "That"} and entity not in matched:
            matched.append(entity)
    return matched[:8]


def extract_claims(text: str, entities: list[str] | None = None, max_claims: int = 8) -> list[dict[str, object]]:
    entities = entities or []
    claims: list[dict[str, object]] = []
    seen: set[str] = set()
    for sentence in _split_sentences(text):
        clean = sentence.strip()
        if not _is_candidate_sentence(clean):
            continue
        lowered = clean.lower()
        fingerprint = re.sub(r"\W+", " ", lowered).strip()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        claim_type = _claim_type(clean)
        attributed = any(re.search(pattern, lowered) for pattern in ATTRIBUTION_PATTERNS)
        confidence = 0.72
        if claim_type == "number":
            confidence += 0.10
        if attributed:
            confidence += 0.08
        if re.search(r"\bpassed\b|\bapproved\b|\bannounced\b|\bconfirmed\b|\breleased\b", lowered):
            confidence += 0.05
        matched_entities = _match_entities(clean, entities)
        claims.append(
            {
                "text": clean.rstrip(".") + ".",
                "claim_type": claim_type,
                "entities": matched_entities,
                "confidence_score": round(min(confidence, 0.94), 2),
            }
        )
        if len(claims) >= max_claims:
            break
    return claims
