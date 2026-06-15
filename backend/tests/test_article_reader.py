from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.ingest.article_reader import _ArticleTextParser


class ArticleReaderTest(unittest.TestCase):
    def test_parser_keeps_article_blocks_and_ignores_junk(self):
        parser = _ArticleTextParser()
        parser.feed(
            """
            <html>
              <body>
                <nav>This navigation block should not appear in the extracted article text.</nav>
                <p>Officials said the agency opened a review after three sources reported the same shipment delay.</p>
                <p>Subscribe to our newsletter for more alerts and promotions.</p>
                <p>The review is expected to include port records, company filings, and public shipping notices.</p>
              </body>
            </html>
            """
        )
        self.assertEqual(len(parser.blocks), 2)
        self.assertIn("shipment delay", parser.blocks[0])
        self.assertNotIn("newsletter", " ".join(parser.blocks).lower())


if __name__ == "__main__":
    unittest.main()
