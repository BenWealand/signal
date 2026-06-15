from __future__ import annotations


LOADED_WORDS = {
    "slammed",
    "shocking",
    "chaos",
    "disaster",
    "furious",
    "bombshell",
    "crisis",
}


def framing_score(text: str) -> float:
    words = [word.strip(".,!?;:").lower() for word in text.split()]
    if not words:
        return 0.0
    return round(sum(1 for word in words if word in LOADED_WORDS) / len(words), 3)

