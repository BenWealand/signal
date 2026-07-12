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
from app import auth as auth_mod


class AdminAccessTest(unittest.TestCase):
    def test_default_admin_email_includes_ben(self):
        emails = admin_email_set()
        self.assertIn("benwealand@gmail.com", emails)

    def test_require_admin_rejects_missing_jwt_secret(self):
        auth_mod.settings = SimpleNamespace(
            supabase_jwt_secret="",
            admin_emails="benwealand@gmail.com",
            signal_api_token="",
        )
        with self.assertRaises(HTTPException) as ctx:
            routes_admin._require_admin("")
        self.assertEqual(ctx.exception.status_code, 503)
        auth_mod.settings = __import__("app.config", fromlist=["settings"]).settings

    def test_require_admin_rejects_non_admin_email(self):
        with patch.object(auth_mod, "decode_supabase_jwt", return_value={"sub": "u", "email": "other@example.com"}):
            with patch.object(
                auth_mod,
                "sync_user_from_claims",
                return_value={"id": 7, "email": "other@example.com", "role": "reader", "name": "O"},
            ):
                with patch("app.auth.admin_email_set", return_value={"benwealand@gmail.com"}):
                    with self.assertRaises(HTTPException) as ctx:
                        routes_admin._require_admin("Bearer fake")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_require_admin_allows_ben(self):
        with patch.object(auth_mod, "decode_supabase_jwt", return_value={"sub": "u", "email": "benwealand@gmail.com"}):
            with patch.object(
                auth_mod,
                "sync_user_from_claims",
                return_value={"id": 1, "email": "benwealand@gmail.com", "role": "admin", "name": "Ben"},
            ):
                with patch("app.auth.admin_email_set", return_value={"benwealand@gmail.com"}):
                    user = routes_admin._require_admin("Bearer fake")
        self.assertEqual(user["id"], 1)


if __name__ == "__main__":
    unittest.main()
