from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingest.source_ranker import evaluate_source_quality, rank_sources, source_score


def article(
    url: str,
    title: str,
    raw_text: str,
    *,
    source_name: str = "Outlet",
    published_at: str = "2026-05-29T12:00:00Z",
    reliability_tier: str = "standard",
) -> dict:
    return {
        "source_name": source_name,
        "domain": url.split("/")[2].removeprefix("www."),
        "title": title,
        "url": url,
        "published_at": published_at,
        "description": raw_text[:160],
        "raw_text": raw_text,
        "reliability_tier": reliability_tier,
    }


class SourceRankerTest(unittest.TestCase):
    def test_ranks_reliable_recent_relevant_full_text_sources_first(self):
        prompt = "latest senate budget vote"
        strong = article(
            "https://apnews.com/article/budget-vote",
            "Senate passes budget bill in 54-46 vote",
            "The Senate passed the budget bill in a 54-46 vote. " * 30,
            source_name="Associated Press",
            reliability_tier="high",
        )
        weak = article(
            "https://exampleblog.com/post",
            "One comment on budget politics",
            "Short note about politics.",
            published_at="2026-04-01T12:00:00Z",
        )

        ranked, meta = rank_sources([weak, strong], prompt, now=datetime(2026, 5, 29, tzinfo=timezone.utc))

        self.assertEqual(ranked[0]["url"], strong["url"])
        self.assertGreater(source_score(strong, prompt), source_score(weak, prompt))
        self.assertEqual(meta["usable_source_count"], 1)

    def test_filters_stale_aggregator_social_and_low_text_candidates(self):
        prompt = "latest senate budget vote"
        current = article(
            "https://reuters.com/world/us/senate-budget-vote",
            "Senate budget vote latest update",
            "The Senate budget vote remained the focus of talks. " * 20,
            source_name="Reuters",
            reliability_tier="high",
        )
        stale = article(
            "https://bbc.com/news/old-budget",
            "Senate budget vote update",
            "The Senate budget vote remained the focus of talks. " * 20,
            published_at="2026-03-01T12:00:00Z",
        )
        social = article("https://x.com/someone/status/1", "Senate budget vote", "The Senate budget vote.")
        aggregator = article("https://news.google.com/articles/abc", "Senate budget vote", "The Senate budget vote.")
        short = article("https://example.com/short", "Senate budget vote", "too short")

        ranked, meta = rank_sources(
            [stale, social, aggregator, short, current],
            prompt,
            now=datetime(2026, 5, 29, tzinfo=timezone.utc),
            min_text_chars=80,
        )

        self.assertEqual([item["url"] for item in ranked], [current["url"]])
        self.assertIn("stale_for_current_prompt", meta["rejected"])
        self.assertIn("blocked_domain", meta["rejected"])
        self.assertIn("aggregator_url", meta["rejected"])
        self.assertIn("insufficient_text", meta["rejected"])

    def test_quality_gate_reports_domain_and_text_failures(self):
        prompt = "senate budget vote"
        items = [
            article(f"https://apnews.com/article/{idx}", "Senate budget vote", "short text " * 20)
            for idx in range(2)
        ]

        quality = evaluate_source_quality(items, prompt)

        self.assertEqual(quality["level"], "limited")
        self.assertIn("minimum_usable_source_count", quality["failed_gates"])
        self.assertIn("minimum_domain_diversity", quality["failed_gates"])


if __name__ == "__main__":
    unittest.main()
