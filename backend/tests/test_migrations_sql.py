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


if __name__ == "__main__":
    unittest.main()
