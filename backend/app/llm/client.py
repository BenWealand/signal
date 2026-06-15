from __future__ import annotations

from app.config import settings


def has_openai_key() -> bool:
    return bool(settings.openai_api_key.strip())


def complete_text(prompt: str, model: str = "gpt-5-nano") -> str:
    if not has_openai_key():
        raise RuntimeError("OPENAI_API_KEY is not set. Local rule-based MVP mode is active.")

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.responses.create(
        model=model,
        input=prompt,
    )
    return response.output_text
