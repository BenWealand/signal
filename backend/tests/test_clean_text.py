from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.processing.clean_text import clean_article_text


class CleanTextTest(unittest.TestCase):
    def test_removes_junk_and_whitespace(self):
        text = clean_article_text("Lead.   Advertisement\n\nSubscribe to our newsletter.")
        self.assertEqual(text, "Lead.")


if __name__ == "__main__":
    unittest.main()

