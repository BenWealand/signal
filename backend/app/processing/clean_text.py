from __future__ import annotations

import html
import re


JUNK_PATTERNS = [
    r"subscribe to our newsletter\.?",
    r"sign up for .+ alerts\.?",
    r"advertisement\.?",
    r"continue reading\.?",
    r"all rights reserved\.?",
]


def clean_article_text(raw_text: str) -> str:
    # Decode HTML entities (&nbsp; &amp; etc.) before any other processing
    text = html.unescape(raw_text)
    text = text.replace("\r", "\n")
    # Replace non-breaking spaces and zero-width chars with regular spaces
    text = re.sub(r"[\xa0\u200b\u200c\u200d\ufeff]", " ", text)
    for pattern in JUNK_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
