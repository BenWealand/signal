from __future__ import annotations

import html
import re


def search_prompt_from_x_post(text: str) -> str:
    """Turn an X post into a bounded neutral search string without an LLM."""
    cleaned = html.unescape(str(text or ""))
    cleaned = re.sub(r"https?://\S+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?<!\w)@[A-Za-z0-9_]{1,15}\b", " ", cleaned)
    cleaned = re.sub(r"\b(?:utm_[a-z_]+|fbclid|gclid)=[^\s&]+", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"#([A-Za-z0-9_]+)", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—:;,")
    return cleaned[:240].rstrip()
