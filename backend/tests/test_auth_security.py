from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import auth as auth_mod
from app.api import routes_admin


class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        self._settings = auth_mod.settings
        self._admin_settings = routes_admin.settings

    def tearDown(self):
        auth_mod.settings = self._settings
        routes_admin.settings = self._admin_settings

    def test_permissions_for_admin(self):
        perms = auth_mod.permissions_for_role("admin")
        self.assertTrue(perms["adminTerminal"])
        self.assertTrue(perms["manageXAgent"])
        self.assertTrue(perms["manageUsers"])

    def test_permissions_for_reader(self):
        perms = auth_mod.permissions_for_role("reader")
        self.assertFalse(perms["adminTerminal"])
        self.assertTrue(perms["saveArticles"])

    def test_resolve_role_elevates_allowlisted_email(self):
        auth_mod.settings = SimpleNamespace(admin_emails="benwealand@gmail.com")
        # admin_email_set reads from app.config.settings — patch that too
        with patch("app.auth.admin_email_set", return_value={"benwealand@gmail.com"}):
            self.assertEqual(auth_mod.resolve_role_for_email("BenWealand@gmail.com", "reader"), "admin")
            self.assertEqual(auth_mod.resolve_role_for_email("other@example.com", "reader"), "reader")

    def test_sync_user_from_claims_requires_email(self):
        with self.assertRaises(HTTPException) as ctx:
            auth_mod.sync_user_from_claims({"sub": "abc"}, touch_login=False)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_sync_user_from_claims_upserts(self):
        claims = {
            "sub": "11111111-1111-1111-1111-111111111111",
            "email": "reader@example.com",
            "user_metadata": {"name": "Reader One"},
            "amr": [{"method": "password"}],
        }
        fake_user = {
            "id": 9,
            "name": "Reader One",
            "email": "reader@example.com",
            "plan": "Reader",
            "role": "reader",
            "supabase_user_id": claims["sub"],
            "email_confirmed": 1,
        }
        with patch.object(auth_mod.queries, "get_user_by_supabase_id", return_value={}):
            with patch.object(auth_mod.queries, "get_user_by_email", return_value={}):
                with patch.object(auth_mod.queries, "upsert_user", return_value=fake_user) as upsert:
                    with patch("app.auth.admin_email_set", return_value=set()):
                        user = auth_mod.sync_user_from_claims(claims, touch_login=True)
        self.assertEqual(user["id"], 9)
        self.assertTrue(upsert.called)
        kwargs = upsert.call_args.kwargs
        self.assertEqual(kwargs.get("role"), "reader")
        self.assertTrue(kwargs.get("touch_login"))

    def test_require_admin_user_rejects_reader(self):
        auth_mod.settings = SimpleNamespace(
            supabase_jwt_secret="secret",
            admin_emails="benwealand@gmail.com",
        )
        with patch.object(auth_mod, "decode_supabase_jwt", return_value={"sub": "x", "email": "reader@example.com"}):
            with patch.object(
                auth_mod,
                "sync_user_from_claims",
                return_value={"id": 2, "email": "reader@example.com", "role": "reader", "name": "R"},
            ):
                with patch("app.auth.admin_email_set", return_value={"benwealand@gmail.com"}):
                    with self.assertRaises(HTTPException) as ctx:
                        auth_mod.require_admin_user("Bearer fake")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_require_admin_user_allows_admin_role(self):
        with patch.object(auth_mod, "decode_supabase_jwt", return_value={"sub": "x", "email": "benwealand@gmail.com"}):
            with patch.object(
                auth_mod,
                "sync_user_from_claims",
                return_value={"id": 1, "email": "benwealand@gmail.com", "role": "admin", "name": "Ben"},
            ):
                with patch("app.auth.admin_email_set", return_value={"benwealand@gmail.com"}):
                    user = auth_mod.require_admin_user("Bearer fake")
        self.assertEqual(user["id"], 1)

    def test_public_user_view_includes_permissions(self):
        view = auth_mod.public_user_view({
            "id": 3,
            "name": "Ed",
            "email": "ed@example.com",
            "role": "editor",
            "plan": "Reader",
        })
        self.assertEqual(view["role"], "editor")
        self.assertTrue(view["permissions"]["writeArticles"])
        self.assertFalse(view["permissions"]["adminTerminal"])

    def test_decode_hs256_with_secret(self):
        import time
        import jwt as pyjwt

        secret = "test-hs-secret"
        token = pyjwt.encode(
            {
                "sub": "user-hs",
                "email": "hs@example.com",
                "aud": "authenticated",
                "exp": int(time.time()) + 3600,
            },
            secret,
            algorithm="HS256",
        )
        auth_mod.settings = SimpleNamespace(supabase_jwt_secret=secret, supabase_url="")
        auth_mod._jwks_clients.clear()
        claims = auth_mod.decode_supabase_jwt(f"Bearer {token}")
        self.assertEqual(claims["email"], "hs@example.com")
        auth_mod.settings = self._settings

    def test_decode_es256_via_jwks(self):
        import time
        from cryptography.hazmat.primitives.asymmetric import ec
        import jwt as pyjwt

        private_key = ec.generate_private_key(ec.SECP256R1())
        token = pyjwt.encode(
            {
                "sub": "user-es",
                "email": "es@example.com",
                "aud": "authenticated",
                "exp": int(time.time()) + 3600,
            },
            private_key,
            algorithm="ES256",
            headers={"kid": "test-kid"},
        )

        class FakeSigningKey:
            def __init__(self, key):
                self.key = key

        class FakeJwks:
            def get_signing_key_from_jwt(self, _token):
                return FakeSigningKey(private_key.public_key())

        auth_mod.settings = SimpleNamespace(
            supabase_jwt_secret="",
            supabase_url="https://example.supabase.co",
        )
        auth_mod._jwks_clients.clear()
        with patch.object(auth_mod, "_get_jwks_client", return_value=FakeJwks()):
            claims = auth_mod.decode_supabase_jwt(f"Bearer {token}")
        self.assertEqual(claims["sub"], "user-es")
        self.assertEqual(claims["email"], "es@example.com")
        auth_mod.settings = self._settings

    def test_decode_rejects_when_neither_url_nor_secret(self):
        auth_mod.settings = SimpleNamespace(supabase_jwt_secret="", supabase_url="")
        with self.assertRaises(HTTPException) as ctx:
            auth_mod.decode_supabase_jwt("Bearer anything")
        self.assertEqual(ctx.exception.status_code, 503)
        auth_mod.settings = self._settings

    def test_hs256_secret_cannot_verify_es256_without_jwks(self):
        """Mirrors production misconfig: JWT secret set but tokens are ES256."""
        import time
        from cryptography.hazmat.primitives.asymmetric import ec
        import jwt as pyjwt

        private_key = ec.generate_private_key(ec.SECP256R1())
        token = pyjwt.encode(
            {
                "sub": "user-es",
                "email": "es@example.com",
                "aud": "authenticated",
                "exp": int(time.time()) + 3600,
            },
            private_key,
            algorithm="ES256",
        )
        auth_mod.settings = SimpleNamespace(supabase_jwt_secret="legacy-hs-secret", supabase_url="")
        auth_mod._jwks_clients.clear()
        with self.assertRaises(HTTPException) as ctx:
            auth_mod.decode_supabase_jwt(f"Bearer {token}")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Invalid", ctx.exception.detail)
        auth_mod.settings = self._settings


class AdminRouteTests(unittest.TestCase):
    def test_admin_me_uses_shared_guard(self):
        with patch.object(routes_admin, "require_admin_user", return_value={
            "id": 1,
            "email": "benwealand@gmail.com",
            "name": "Ben",
            "role": "admin",
        }):
            with patch("app.auth.admin_email_set", return_value={"benwealand@gmail.com"}):
                payload = routes_admin.admin_me(authorization="Bearer x")
        self.assertTrue(payload["admin"])
        self.assertEqual(payload["role"], "admin")

    def test_admin_list_users(self):
        with patch.object(routes_admin, "require_admin_user", return_value={"id": 1, "email": "a@b.com", "role": "admin"}):
            with patch.object(routes_admin.queries, "list_users", return_value=[{
                "id": 2, "name": "R", "email": "r@example.com", "role": "reader", "plan": "Reader",
            }]):
                with patch.object(routes_admin.queries, "count_users", return_value=1):
                    with patch("app.auth.admin_email_set", return_value=set()):
                        payload = routes_admin.admin_list_users(authorization="Bearer x")
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["users"][0]["email"], "r@example.com")

    def test_admin_cannot_demote_self(self):
        with patch.object(routes_admin, "require_admin_user", return_value={"id": 1, "email": "a@b.com", "role": "admin"}):
            with self.assertRaises(HTTPException) as ctx:
                routes_admin.admin_set_user_role(
                    1,
                    routes_admin.AdminRolePayload(role="reader"),
                    authorization="Bearer x",
                )
        self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
