from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.llm.provider import GeminiLLMClient, LocalLLMClient
from app.llm.article_generator import generate_article_package


SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "string"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Make one minimal generation-provider health request")
    parser.add_argument("provider", choices=("gemini", "local"))
    parser.add_argument("--gemini-pool", choices=("demand", "daily"), default="demand")
    parser.add_argument("--article-shape", action="store_true")
    args = parser.parse_args()
    if args.article_shape:
        sample_sources = [
            {
                "source_name": f"Test outlet {index}",
                "title": "Transit authority approves a new weekend service schedule",
                "url": f"https://outlet{index}.example/transit-schedule",
                "raw_text": (
                    "The regional transit authority approved a weekend service schedule after "
                    "a public meeting. Officials said implementation dates and route details "
                    "remain subject to a final published timetable. "
                ) * 5,
            }
            for index in range(1, 5)
        ]
        started = time.monotonic()
        gemini_client = GeminiLLMClient(
            api_keys=(
                [settings.daily_gemini_api_key]
                if args.gemini_pool == "daily"
                else [settings.demand_gemini_api_key, settings.fallback_gemini_api_key]
            ),
            credential_label=f"{args.gemini_pool.upper()} Gemini pool",
        )
        result = generate_article_package(
            "regional transit weekend schedule",
            sample_sources,
            mode="fast",
            source_policy="standard",
            client=gemini_client if args.provider == "gemini" else LocalLLMClient(),
        )
        print(
            f"{args.provider}_article_live=yes "
            f"seconds={time.monotonic() - started:.2f} paragraphs={len(result['body'])}"
        )
        return
    client = (
        GeminiLLMClient(
            api_keys=(
                [settings.daily_gemini_api_key]
                if args.gemini_pool == "daily"
                else [settings.demand_gemini_api_key, settings.fallback_gemini_api_key]
            ),
            credential_label=f"{args.gemini_pool.upper()} Gemini pool",
        )
        if args.provider == "gemini"
        else LocalLLMClient()
    )
    result = client.generate_json(
        messages=[{"role": "user", "content": "Return JSON with ok set to yes."}],
        schema=SCHEMA,
        max_tokens=32,
        temperature=0,
        timeout=30,
    )
    print(f"{args.provider}_live={result.get('ok', 'missing')}")


if __name__ == "__main__":
    main()
