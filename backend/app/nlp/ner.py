from __future__ import annotations

import re
from functools import lru_cache


ENTITY_HINTS = {
    "Senate": "ORG",
    "White House": "ORG",
    "Treasury": "ORG",
    "Reuters": "ORG",
    "Associated Press": "ORG",
    "BBC": "ORG",
    "Washington": "GPE",
    "United States": "GPE",
    "Europe": "GPE",
    "Asia": "GPE",
    "Thursday": "DATE",
    "Monday": "DATE",
}


@lru_cache(maxsize=1)
def _load_spacy_model():
    try:
        import spacy

        return spacy.load("en_core_web_sm")
    except Exception:
        return None


def extract_entities(text: str) -> list[dict[str, object]]:
    nlp = _load_spacy_model()
    if nlp:
        doc = nlp(text)
        return [
            {
                "text": ent.text,
                "type": ent.label_,
                "start_char": ent.start_char,
                "end_char": ent.end_char,
            }
            for ent in doc.ents
            if ent.label_ in {"PERSON", "ORG", "GPE", "DATE", "EVENT", "LAW", "PRODUCT"}
        ]

    found: list[dict[str, object]] = []
    for entity, entity_type in ENTITY_HINTS.items():
        for match in re.finditer(re.escape(entity), text):
            found.append(
                {
                    "text": entity,
                    "type": entity_type,
                    "start_char": match.start(),
                    "end_char": match.end(),
                }
            )

    for match in re.finditer(r"\b[A-Z][a-z]+(?:\s[A-Z][a-z]+){0,2}\b", text):
        value = match.group(0)
        if value in {"The", "Multiple", "Sources"}:
            continue
        found.append(
            {
                "text": value,
                "type": "ORG" if any(token in value for token in ["Agency", "Senate", "House"]) else "PERSON",
                "start_char": match.start(),
                "end_char": match.end(),
            }
        )

    deduped = {}
    for item in found:
        deduped[(item["text"], item["type"], item["start_char"])] = item
    return list(deduped.values())

