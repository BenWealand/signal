from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.llm.claim_extractor import extract_claims


class ClaimExtractionTest(unittest.TestCase):
    def test_extracts_factual_sentence(self):
        claims = extract_claims("The Senate passed the bill on Thursday by a vote of 54-46.")
        self.assertTrue(claims)
        self.assertIn("54-46", claims[0]["text"])

    def test_filters_prediction_and_extracts_attributed_numerical_claims(self):
        text = (
            "Analysts believe the bill could reshape the market next year. "
            "According to the Treasury Department, the program distributed $4.2 billion to states in April. "
            "Subscribe to our newsletter for more updates."
        )
        claims = extract_claims(text, entities=["Treasury Department"])

        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["claim_type"], "attributed")
        self.assertIn("$4.2 billion", claims[0]["text"])
        self.assertIn("Treasury Department", claims[0]["entities"])


if __name__ == "__main__":
    unittest.main()
