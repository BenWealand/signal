from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.llm.gemini_writer import _parse_package_text


class GeminiPackageParseTest(unittest.TestCase):
    def test_parses_tagged_package(self):
        text = """<<<HEADLINE>>>
Senate Passes Budget Bill Overnight
<<<DEK>>>
Lawmakers approved the package after a late floor fight.
<<<BODY>>>
First paragraph with enough detail for validation across the overnight senate vote.

Second paragraph confirming the sourced outcome from multiple public outlets covering the bill.
"""
        package = _parse_package_text(text)
        self.assertEqual(package["headline"], "Senate Passes Budget Bill Overnight")
        self.assertIn("Lawmakers approved", package["dek"])
        self.assertIn("First paragraph", package["body"])

    def test_parses_json_package(self):
        text = """{
  "headline": "Markets Rally After Rate Decision",
  "dek": "Investors digested the central bank statement within minutes.",
  "body": "First paragraph about the rally and what traders watched in the statement.\\n\\nSecond paragraph about yields, futures, and the immediate market reaction."
}"""
        package = _parse_package_text(text)
        self.assertEqual(package["headline"], "Markets Rally After Rate Decision")
        self.assertIn("Investors digested", package["dek"])
        self.assertIn("First paragraph", package["body"])


if __name__ == "__main__":
    unittest.main()
