from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import urllib.error

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.llm.article_generator import ARTICLE_SCHEMA, generate_article_package, prepare_sources
from app.llm.provider import GeminiLLMClient, LLMSchemaError, LLMTransportError, LocalLLMClient
from app.processing import article_writer
from app.jobs import article_worker


def sources(count: int = 7) -> list[dict]:
    return [
        {
            "source_name": f"Outlet {index}",
            "title": f"Outlet {index} reports the same concrete event",
            "url": f"https://outlet{index}.example/story?utm_source=test",
            "raw_text": (f"Outlet {index} independently reports the concrete event and its effects. " * 40),
        }
        for index in range(count)
    ]


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class LocalLLMArchitectureTests(unittest.TestCase):
    @patch("app.llm.article_generator.LocalLLMClient")
    @patch("app.llm.article_generator.GeminiLLMClient")
    def test_provider_routing_keeps_x_local_and_website_on_gemini(self, gemini_cls, local_cls):
        package = {
            "headline": "A concrete writer headline",
            "dek": "A concise summary grounded in the supplied reporting.",
            "body": ["A" * 90, "B" * 90, "C" * 90, "D" * 90],
        }
        gemini_cls.return_value.generate_json.return_value = package
        local_cls.return_value.generate_json.return_value = package

        generate_article_package("website event", sources(), mode="fast")
        generate_article_package(
            "x event",
            [{
                "source_name": "@desk on X",
                "title": "A concrete event",
                "url": "https://x.com/desk/status/1",
                "raw_text": "A concrete event with enough attributable context for the response.",
            }],
            mode="fast",
            source_policy="x_response",
        )

        gemini_cls.return_value.generate_json.assert_called_once()
        local_cls.return_value.generate_json.assert_called_once()

    @patch("app.llm.provider.time.sleep")
    @patch("app.llm.provider.random.uniform", return_value=0.0)
    @patch("app.llm.provider.urllib.request.urlopen")
    def test_gemini_rotates_keys_after_429(self, urlopen, _jitter, sleep):
        rate_limit = urllib.error.HTTPError(
            "https://example.test", 429, "Too Many Requests", {"Retry-After": "1"}, None
        )
        package = {
            "headline": "A concrete Gemini headline",
            "dek": "A concise summary grounded in the supplied reporting.",
            "body": ["A" * 90, "B" * 90, "C" * 90],
        }
        urlopen.side_effect = [
            rate_limit,
            _Response({"candidates": [{"content": {"parts": [{"text": json.dumps(package)}]}}]}),
        ]
        provider_settings = SimpleNamespace(
            gemini_api_keys="", gemini_api_key="", gemini_model="gemini-flash-latest",
            gemini_retry_attempts=3, gemini_retry_base_seconds=2,
            gemini_retry_max_seconds=45, gemini_timeout_seconds=90, llm_top_p=0.9,
        )
        with patch("app.llm.provider.settings", provider_settings):
            result = GeminiLLMClient(api_keys=["key-one", "key-two"]).generate_json(
                messages=[{"role": "user", "content": "test"}],
                schema=ARTICLE_SCHEMA,
                max_tokens=700,
                temperature=0.15,
                top_p=0.9,
                timeout=5,
            )
        self.assertEqual(result, package)
        self.assertEqual(urlopen.call_args_list[0].args[0].headers["X-goog-api-key"], "key-one")
        self.assertEqual(urlopen.call_args_list[1].args[0].headers["X-goog-api-key"], "key-two")
        payload = json.loads(urlopen.call_args_list[1].args[0].data)
        generation = payload["generationConfig"]
        self.assertEqual(generation["responseMimeType"], "application/json")
        self.assertNotIn(
            "maxLength",
            generation["responseJsonSchema"]["properties"]["headline"],
        )
        sleep.assert_called_once_with(1.0)

    def test_article_package_strips_model_markdown_artifacts(self):
        client = Mock()
        client.generate_json.return_value = {
            "headline": "**Concrete** event",
            "dek": "A *sourced* account of the event.",
            "body": [f"Paragraph with **verified detail** {index}. " + "A" * 90 for index in range(4)],
        }
        result = generate_article_package("concrete event", sources(), mode="fast", client=client)
        self.assertEqual(result["headline"], "Concrete event")
        self.assertEqual(result["dek"], "A sourced account of the event.")
        self.assertNotIn("**", " ".join(result["body"]))

    def test_fast_mode_uses_compact_schema_and_source_prompt(self):
        client = Mock()
        client.generate_json.return_value = {
            "headline": "Concrete event",
            "dek": "A sourced account of the event.",
            "body": [f"Paragraph {index}. " + "A" * 90 for index in range(4)],
        }
        generate_article_package("concrete event", sources(6), mode="fast", client=client)
        call = client.generate_json.call_args.kwargs
        self.assertEqual(call["schema"]["properties"]["body"]["maxItems"], 4)
        self.assertEqual(call["schema"]["properties"]["body"]["items"]["maxLength"], 800)
        self.assertEqual(call["messages"][1]["content"].count("SOURCE "), 4)

    def test_source_preparation_is_independent_and_bounded(self):
        prepared = prepare_sources(sources(), total_chars=8500)
        self.assertEqual(len(prepared), 6)
        self.assertEqual(len({item["url"].split("/")[2] for item in prepared}), 6)
        self.assertLessEqual(sum(len(item["text"]) for item in prepared), 8500)
        self.assertTrue(all("utm_source" not in item["url"] for item in prepared))

    @patch("app.llm.provider.urllib.request.urlopen")
    def test_provider_sends_native_schema_response_format(self, urlopen):
        package = {
            "headline": "A concrete local writer headline",
            "dek": "A concise summary grounded in the supplied reporting.",
            "body": ["A" * 90, "B" * 90, "C" * 90],
        }
        urlopen.return_value = _Response(
            {"choices": [{"message": {"content": json.dumps(package)}}]}
        )
        result = LocalLLMClient(base_url="http://127.0.0.1:8080/v1").generate_json(
            messages=[{"role": "user", "content": "test"}],
            schema=ARTICLE_SCHEMA,
            max_tokens=950,
            temperature=0.15,
            top_p=0.9,
            timeout=5,
        )
        self.assertEqual(result, package)
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["response_format"], {"type": "json_schema", "schema": ARTICLE_SCHEMA})
        self.assertEqual(payload["max_tokens"], 950)

    @patch("app.llm.provider.urllib.request.urlopen")
    def test_provider_recovers_complete_paragraphs_from_truncated_trailing_json(self, urlopen):
        content = json.dumps({
            "headline": "A concrete local writer headline",
            "dek": "A concise summary grounded in supplied reporting.",
            "body": ["A" * 90, "B" * 90, "C" * 90],
        })
        content = content[:-2] + ', "unfinished trailing paragraph'
        urlopen.return_value = _Response({"choices": [{"message": {"content": content}}]})
        result = LocalLLMClient(base_url="http://127.0.0.1:8080/v1").generate_json(
            messages=[{"role": "user", "content": "test"}],
            schema=ARTICLE_SCHEMA,
            max_tokens=700,
            temperature=0.15,
            top_p=0.9,
            timeout=5,
        )
        self.assertEqual(len(result["body"]), 3)
        self.assertEqual(result["body"][2], "C" * 90)

    def test_generation_retries_schema_failure_once(self):
        client = Mock()
        valid = {
            "headline": "A concrete local writer headline",
            "dek": "A concise summary grounded in the supplied reporting.",
            "body": ["A" * 90, "B" * 90, "C" * 90, "D" * 90],
        }
        client.generate_json.side_effect = [LLMSchemaError("bad"), valid]
        result = generate_article_package("concrete event", sources(), mode="fast", client=client)
        self.assertEqual(result, valid)
        self.assertEqual(client.generate_json.call_count, 2)

    def test_generation_does_not_retry_unexpected_failures(self):
        client = Mock()
        client.generate_json.side_effect = RuntimeError("programming error")
        with self.assertRaises(RuntimeError):
            generate_article_package("concrete event", sources(), mode="fast", client=client)
        client.generate_json.assert_called_once()

    def test_x_response_policy_accepts_one_attributed_origin(self):
        client = Mock()
        valid = {
            "headline": "Originating post draws attention",
            "dek": "The claim remains unverified beyond the attributed post.",
            "body": ["A" * 90, "B" * 90, "C" * 90, "D" * 90],
        }
        client.generate_json.return_value = valid
        origin = [{
            "source_name": "@desk on X",
            "title": "A concrete breaking claim",
            "url": "https://x.com/desk/status/123",
            "raw_text": "A concrete breaking claim with enough context to explain what was posted.",
        }]
        result = generate_article_package(
            "concrete breaking claim",
            origin,
            mode="fast",
            source_policy="x_response",
            client=client,
        )
        self.assertEqual(result, valid)
        user_prompt = client.generate_json.call_args.kwargs["messages"][1]["content"]
        self.assertIn("do not imply independent corroboration", user_prompt)

    def test_standard_fast_policy_still_rejects_one_source(self):
        with self.assertRaisesRegex(LLMSchemaError, "two independent"):
            generate_article_package("concrete claim", sources(1), mode="fast", client=Mock())

    def test_standard_thorough_policy_requires_four_sources(self):
        with self.assertRaisesRegex(LLMSchemaError, "four independent"):
            generate_article_package("concrete claim", sources(3), mode="thorough", client=Mock())

    def test_section_fast_policy_accepts_two_sources_with_limited_coverage_instruction(self):
        client = Mock()
        valid = {
            "headline": "Two outlets report a concrete development",
            "dek": "A concise account of the limited available reporting.",
            "body": ["A" * 90, "B" * 90, "C" * 90, "D" * 90],
        }
        client.generate_json.return_value = valid
        result = generate_article_package(
            "concrete development",
            sources(2),
            mode="fast",
            source_policy="section_fast",
            client=client,
        )
        self.assertEqual(result, valid)
        prompt = client.generate_json.call_args.kwargs["messages"][1]["content"]
        self.assertIn("limited source coverage", prompt)

    @patch.object(article_writer.queries, "search_articles_fts")
    @patch.object(article_writer.queries, "search_recent_articles_by_entities")
    @patch.object(article_writer, "extract_entities")
    def test_daily_entity_matches_are_reused_before_text_search(self, entities, entity_search, text_search):
        entities.return_value = [{"text": "Acme Corp", "type": "ORG"}]
        entity_search.return_value = [{
            "id": 7,
            "source_name": "Wire",
            "title": "Different wording for the same development",
            "url": "https://wire.example/acme",
            "raw_text": "Sourced reporting about the development. " * 10,
            "entity_match_count": 1,
        }]
        text_search.return_value = []
        rows = article_writer._cached_articles_for_prompt("Acme Corp announces expansion", 4)
        self.assertEqual([row["id"] for row in rows], [7])
        entity_search.assert_called_once_with(["acme corp"], hours=24, limit=18)

    def test_cache_websearch_query_prioritizes_entities_and_uses_or_terms(self):
        query = article_writer._cache_websearch_query(
            "Acme Corp announces a major expansion in Canada",
            ["acme corp", "canada"],
        )
        self.assertTrue(query.startswith('"acme corp" OR canada'))
        self.assertIn(" OR expansion", query)

    @patch.object(article_writer, "fetch_gdelt_articles")
    @patch.object(article_writer, "fetch_articles_for_query_fast")
    @patch.object(article_writer, "_cached_articles_for_prompt")
    def test_sufficient_cache_skips_live_providers(self, cache_lookup, rss_lookup, gdelt_lookup):
        cache_lookup.return_value = [
            {
                "id": index,
                "source_name": f"Source {index}",
                "title": "Acme expansion announced",
                "url": f"https://source{index}.example/acme",
                "raw_text": "Acme expansion details " * 20,
            }
            for index in range(1, 5)
        ]
        rows = article_writer._source_candidates_for_variant(
            "Acme expansion announced",
            8,
            "fast",
        )
        self.assertEqual(len(rows), 4)
        rss_lookup.assert_not_called()
        gdelt_lookup.assert_not_called()

    def test_relevance_helpers_tolerate_null_article_text(self):
        article = {"title": "Acme update", "clean_text": None, "raw_text": None}
        self.assertIsInstance(article_writer._article_keywords(article), frozenset)
        self.assertFalse(article_writer._is_relevant(article, "unrelated event", frozenset({"unrelated", "event"})))

    @patch.object(article_writer.queries, "find_recent_generated_article_by_fingerprint", return_value={})
    @patch.object(article_writer, "_select_supported_variant")
    @patch.object(article_writer, "_source_candidates_for_variant", return_value=[])
    def test_x_response_uses_one_source_pass(self, one_pass, multi_variant, _recent):
        origin = [{
            "source_kind": "x-post",
            "source_name": "@desk on X",
            "title": "Acme announces an event",
            "url": "https://x.com/desk/status/1",
            "raw_text": "Acme announces a concrete event with enough detail.",
        }]
        selected, prepared, _fingerprint, _existing = article_writer.prepare_article_request(
            "Acme announces an event",
            limit=8,
            mode="fast",
            build_id="build-x",
            supplemental_sources=origin,
            source_policy="x_response",
        )
        self.assertEqual(selected, "Acme announces an event")
        self.assertEqual(prepared, origin)
        one_pass.assert_called_once()
        multi_variant.assert_not_called()

    @patch.object(article_writer.queries, "find_recent_generated_article_by_fingerprint", return_value={})
    @patch.object(article_writer, "_fast_article_from_prompt")
    @patch.object(article_writer, "_select_supported_variant")
    def test_writer_selects_sources_before_one_generation(
        self,
        select_variant,
        fast_writer,
        _find_recent,
    ):
        select_variant.return_value = ("concrete event official announcement", sources())
        fast_writer.return_value = {"id": "a1", "prompt": "selected"}
        result = article_writer.write_article_from_prompt(
            "concrete event",
            mode="fast",
            build_id="build-test",
        )
        fast_writer.assert_called_once()
        self.assertEqual(fast_writer.call_args.kwargs["prefetched_sources"], sources())
        self.assertEqual(result["prompt"], "concrete event")
        self.assertTrue(result["promptAdjusted"])
        self.assertEqual(len(result["sourceFingerprint"]), 64)

    @patch.object(article_worker._image_executor, "submit")
    @patch.object(article_worker, "set_build_progress")
    @patch.object(article_worker, "write_article_from_prompt")
    @patch.object(article_worker, "prepare_article_request")
    @patch.object(article_worker.queries, "update_article_generation_job")
    @patch.object(article_worker.queries, "mark_article_generation_job_ready")
    @patch.object(article_worker.queries, "claim_ready_article_generation_job")
    @patch.object(article_worker.queries, "save_generated_article")
    @patch.object(article_worker.queries, "claim_next_article_generation_job")
    def test_worker_is_the_single_persistence_owner(
        self,
        claim,
        save,
        claim_ready,
        mark_ready,
        update,
        prepare,
        write,
        _progress,
        image_submit,
    ):
        claimed = {
            "id": "build-1",
            "prompt": "concrete event",
            "mode": "fast",
            "payload": {"limit": 12, "source": "Signal desk"},
        }
        claim.return_value = claimed
        prepared_payload = {
            "limit": 12,
            "source": "Signal desk",
            "_prepared": {
                "variant": "concrete event",
                "sources": sources(),
                "fingerprint": "f" * 64,
            },
        }
        claim_ready.return_value = {**claimed, "status": "generating", "payload": prepared_payload}
        prepare.return_value = ("concrete event", sources(), "f" * 64, {})
        article = {
            "id": "article-1",
            "prompt": "concrete event",
            "headline": "Concrete event headline",
            "dek": "Concrete event dek",
            "summary": "Concrete event summary",
            "body": ["A" * 90] * 4,
            "image": {},
        }

        write.return_value = dict(article)
        self.assertTrue(article_worker.process_next_job())
        claim.assert_called_once_with(lane="all")
        claim_ready.assert_called_once_with(lane="all")
        save.assert_called_once()
        mark_ready.assert_called_once()
        statuses = [call.kwargs["status"] for call in update.call_args_list]
        self.assertEqual(statuses, ["saved"])
        image_submit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
