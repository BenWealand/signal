from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.llm.consensus import detect_consensus


class ConsensusTest(unittest.TestCase):
    def test_supported_claim_requires_multiple_sources(self):
        consensus = detect_consensus(
            [
                {"claim_text": "The Senate passed the bill by a 54-46 vote.", "source_name": "Reuters", "url": "https://reuters.com/a"},
                {"claim_text": "The Senate passed the bill by a 54-46 vote.", "source_name": "AP", "url": "https://apnews.com/b"},
            ],
            use_semantic=False,
        )
        self.assertEqual(consensus[0]["status"], "supported")
        self.assertEqual(consensus[0]["support_count"], 2)

    def test_support_count_uses_distinct_domains_not_source_labels(self):
        consensus = detect_consensus(
            [
                {"claim_text": "The company reported revenue rose 12 percent in April.", "source_name": "Wire Copy", "url": "https://example.com/a"},
                {"claim_text": "The company reported revenue rose 12 percent in April.", "source_name": "Wire Copy", "url": "https://another.com/b"},
            ],
            use_semantic=False,
        )

        self.assertEqual(consensus[0]["status"], "supported")
        self.assertEqual(consensus[0]["support_count"], 2)
        self.assertEqual(set(consensus[0]["source_domains"]), {"example.com", "another.com"})

    def test_conflicting_claims_are_labeled_when_numbers_disagree(self):
        consensus = detect_consensus(
            [
                {"claim_text": "The Senate passed the bill by a 54-46 vote.", "source_name": "Reuters", "url": "https://reuters.com/a"},
                {"claim_text": "The Senate passed the bill by a 52-48 vote.", "source_name": "AP", "url": "https://apnews.com/b"},
            ],
            use_semantic=False,
        )

        self.assertEqual(consensus[0]["status"], "conflicting")


if __name__ == "__main__":
    unittest.main()
