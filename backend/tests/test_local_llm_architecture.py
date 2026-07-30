from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.llm.article_generator import ARTICLE_SCHEMA, generate_article_package, prepare_sources
from app.llm.provider import LLMSchemaError, LLMTransportError, LocalLLMClient
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
        self.assertEqual(payload["response_format"], {"type": "json_object", "schema": ARTICLE_SCHEMA})
        self.assertEqual(payload["max_tokens"], 950)

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
        save.assert_called_once()
        mark_ready.assert_called_once()
        statuses = [call.kwargs["status"] for call in update.call_args_list]
        self.assertEqual(statuses, ["saved"])
        image_submit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
