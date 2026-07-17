from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.migrations import _split_sql


class MigrationSqlSplitTests(unittest.TestCase):
    def test_splits_plain_statements(self):
        sql = "ALTER TABLE users ADD COLUMN role TEXT; CREATE INDEX idx ON users(role);"
        parts = _split_sql(sql)
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0].startswith("ALTER TABLE"))
        self.assertTrue(parts[1].startswith("CREATE INDEX"))

    def test_keeps_dollar_quoted_block(self):
        sql = """
        DO $$
        BEGIN
          IF true THEN
            PERFORM 1;
          END IF;
        END $$;
        CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);
        """
        parts = _split_sql(sql)
        self.assertEqual(len(parts), 2)
        self.assertIn("DO $$", parts[0])
        self.assertIn("END $$", parts[0])
        self.assertTrue(parts[1].startswith("CREATE INDEX"))

    def test_ignores_semicolons_in_strings(self):
        sql = "INSERT INTO t(v) VALUES ('a;b'); SELECT 1;"
        parts = _split_sql(sql)
        self.assertEqual(len(parts), 2)
        self.assertIn("'a;b'", parts[0])

    def test_x_article_share_migration_has_idempotency_index(self):
        path = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations" / "0005_x_article_shares.sql"
        sql = path.read_text(encoding="utf-8")
        parts = _split_sql(sql)
        self.assertGreaterEqual(len(parts), 3)
        self.assertIn("CREATE TABLE IF NOT EXISTS x_article_shares", parts[0])
        self.assertIn("WHERE status = 'posted'", sql)

    def test_x_article_share_reply_migration_adds_target_fields(self):
        path = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations" / "0006_x_article_share_replies.sql"
        sql = path.read_text(encoding="utf-8")
        parts = _split_sql(sql)
        self.assertEqual(len(parts), 2)
        self.assertIn("reply_to_post_id", sql)
        self.assertIn("reply_url", sql)

    def test_generated_article_image_migration_adds_metadata_field(self):
        path = Path(__file__).resolve().parents[1] / "app" / "db" / "migrations" / "0007_generated_article_images.sql"
        sql = path.read_text(encoding="utf-8")
        parts = _split_sql(sql)
        self.assertEqual(len(parts), 1)
        self.assertIn("ADD COLUMN IF NOT EXISTS image", sql)


if __name__ == "__main__":
    unittest.main()
