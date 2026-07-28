"""Deprecated compatibility shim.

All article LLM calls now go through OpenCode Zen (`zen_writer.py`).
Import from `app.llm.zen_writer` in new code.
"""

from app.llm.zen_writer import *  # noqa: F403
from app.llm.zen_writer import (  # noqa: F401
    _active_model,
    _alternate_model,
    _build_source_block,
    _call_zen_chat,
    _clear_last_error,
    _emit_stream_progress,
    _http_error_details,
    _message_content,
    _package_prompt,
    _parse_package_text,
    _rate_limited,
    _record_429,
    _set_last_error,
    _sleep_before_retry,
    _source_budgets,
    _validated_package,
    describe_last_gemini_error,
    describe_last_zen_error,
    generic_news_prompt_from_x_posts_with_gemini,
    generic_news_prompt_from_x_posts_with_zen,
    get_last_gemini_error,
    get_last_zen_error,
    match_x_posts_to_articles_with_gemini,
    match_x_posts_to_articles_with_zen,
    suggest_follow_up_prompts_with_gemini,
    suggest_follow_up_prompts_with_zen,
    suggest_image_queries_with_gemini,
    suggest_image_queries_with_zen,
    write_article_header_with_gemini,
    write_article_header_with_zen,
    write_article_package_with_gemini,
    write_article_package_with_zen,
    write_article_with_gemini,
    write_article_with_zen,
)

# Preserve the old private name some tests may reference.
_call_gemini_package = _call_zen_chat
