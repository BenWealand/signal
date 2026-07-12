from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import admin_email_set
from app.api import routes_admin


class AdminAccessTests(unittest.TestCase):
    def setUp(self):
        self._settings = routes_admin.settings

    def tearDown(self):
        routes_admin.settings = self._settings

    def test_default_admin_email_includes_ben(self):
        emails = admin_email_set()
        self.assertIn("benwealand@gmail.com", emails)

    def test_require_admin_rejects_missing_jwt_secret(self):
        routes_admin.settings = SimpleNamespace(
            supabase_jwt_secret="",
            admin_emails="benwealand@gmail.com",
        )
        with self.assertRaises(HTTPException) as ctx:
            routes_admin._require_admin("")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_require_admin_rejects_non_admin_email(self):
        routes_admin.settings = SimpleNamespace(
            supabase_jwt_secret="secret",
            admin_emails="benwealand@gmail.com",
        )
        with patch.object(routes_admin, "_user_id_from_supabase_jwt", return_value=7):
            with patch.object(routes_admin.queries, "get_user", return_value={"id": 7, "email": "other@example.com"}):
                with self.assertRaises(HTTPException) as ctx:
                    routes_admin._require_admin("Bearer fake")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_require_admin_allows_ben(self):
        routes_admin.settings = SimpleNamespace(
            supabase_jwt_secret="secret",
            admin_emails="benwealand@gmail.com",
        )
        with patch.object(routes_admin, "_user_id_from_supabase_jwt", return_value=1):
            with patch.object(
                routes_admin.queries,
                "get_user",
                return_value={"id": 1, "email": "BenWealand@gmail.com", "name": "Ben"},
            ):
                user = routes_admin._require_admin("Bearer fake")
        self.assertEqual(user["id"], 1)


if __name__ == "__main__":
    unittest.main()
