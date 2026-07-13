from __future__ import annotations

"""Shared authentication helpers for Supabase JWT + app user rows."""

import time
from collections import defaultdict, deque
from secrets import compare_digest
from typing import Any

try:
    import jwt
    from jwt import PyJWKClient
except ImportError:  # pragma: no cover
    jwt = None
    PyJWKClient = None  # type: ignore[misc, assignment]

from fastapi import Header, HTTPException

from app.config import admin_email_set, settings
from app.db import queries

AUTH_RATE_LIMIT = 20
AUTH_RATE_WINDOW_SECONDS = 60.0
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)

VALID_ROLES = frozenset({"reader", "editor", "admin"})

# Cached JWKS client keyed by URL (Supabase rotates keys; PyJWKClient caches internally).
_jwks_clients: dict[str, Any] = {}
_ASYMMETRIC_ALGS = ("ES256", "RS256")


def extract_bearer_token(authorization: str) -> str:
    prefix = "Bearer "
    if authorization.startswith(prefix):
        return authorization[len(prefix):].strip()
    return ""


def check_auth_rate_limit(key: str, *, limit: int = AUTH_RATE_LIMIT) -> None:
    now = time.monotonic()
    bucket = _rate_buckets[key]
    while bucket and now - bucket[0] > AUTH_RATE_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Too many auth requests. Try again shortly.")
    bucket.append(now)


def supabase_auth_configured() -> bool:
    """True when JWT verification can run via JWKS (SUPABASE_URL) and/or HS256 secret."""
    return bool(
        (getattr(settings, "supabase_url", "") or "").strip()
        or (getattr(settings, "supabase_jwt_secret", "") or "").strip()
    )


def _supabase_jwks_url() -> str:
    base = (getattr(settings, "supabase_url", "") or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/auth/v1/.well-known/jwks.json"


def _get_jwks_client():
    if jwt is None or PyJWKClient is None:
        return None
    url = _supabase_jwks_url()
    if not url:
        return None
    client = _jwks_clients.get(url)
    if client is None:
        # lifespan keeps JWKS fresh; cache_keys=True is default in recent PyJWT
        client = PyJWKClient(url, cache_keys=True, lifespan=600)
        _jwks_clients[url] = client
    return client


def _decode_token(token: str, key: Any, algorithms: list[str]) -> dict[str, Any]:
    assert jwt is not None
    try:
        return jwt.decode(
            token,
            key,
            algorithms=algorithms,
            audience="authenticated",
            options={"require": ["exp", "sub"]},
            leeway=30,
        )
    except jwt.InvalidAudienceError:
        return jwt.decode(
            token,
            key,
            algorithms=algorithms,
            options={"verify_aud": False, "require": ["exp", "sub"]},
            leeway=30,
        )


def decode_supabase_jwt(authorization: str) -> dict[str, Any]:
    """
    Verify a Supabase access token.

    Modern Supabase projects sign with ES256 and publish keys at
    `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`. Older / legacy projects
    still use HS256 with the dashboard JWT secret.
    """
    if jwt is None:
        raise HTTPException(status_code=503, detail="JWT authentication dependency is not installed")
    if not supabase_auth_configured():
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured (SUPABASE_URL or SUPABASE_JWT_SECRET)",
        )

    token = extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    last_error: Exception | None = None

    jwks_client = _get_jwks_client()
    if jwks_client is not None:
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            return _decode_token(token, signing_key.key, list(_ASYMMETRIC_ALGS))
        except Exception as exc:  # network / kid / alg / signature
            last_error = exc

    secret = (getattr(settings, "supabase_jwt_secret", "") or "").strip()
    if secret:
        try:
            return _decode_token(token, secret, ["HS256"])
        except jwt.PyJWTError as exc:
            last_error = exc

    raise HTTPException(status_code=401, detail="Invalid authentication token") from last_error


def _claims_email(claims: dict[str, Any]) -> str:
    email = str(claims.get("email") or "").strip().lower()
    if email:
        return email
    meta = claims.get("user_metadata") or {}
    if isinstance(meta, dict):
        return str(meta.get("email") or "").strip().lower()
    return ""


def _claims_name(claims: dict[str, Any], email: str) -> str:
    meta = claims.get("user_metadata") or {}
    if isinstance(meta, dict):
        name = str(meta.get("name") or meta.get("full_name") or "").strip()
        if name:
            return name[:120]
    local = email.split("@", 1)[0] if email else "Reader"
    return (local or "Reader")[:120]


def _claims_email_confirmed(claims: dict[str, Any]) -> bool:
    if claims.get("email_confirmed_at") or claims.get("confirmed_at"):
        return True
    meta = claims.get("user_metadata") or {}
    if isinstance(meta, dict) and meta.get("email_verified") is True:
        return True
    # Many Supabase access tokens omit confirmation timestamps; treat authenticated
    # sessions as confirmed unless explicitly marked false.
    amr = claims.get("amr")
    if isinstance(amr, list) and amr:
        return True
    return bool(claims.get("sub"))


def resolve_role_for_email(email: str, current_role: str | None = None) -> str:
    cleaned = (email or "").strip().lower()
    role = (current_role or "reader").strip().lower()
    if role not in VALID_ROLES:
        role = "reader"
    if cleaned and cleaned in admin_email_set():
        return "admin"
    return role


def permissions_for_role(role: str) -> dict[str, bool]:
    normalized = (role or "reader").strip().lower()
    is_admin = normalized == "admin"
    is_editor = normalized in {"editor", "admin"}
    return {
        "readPublic": True,
        "saveArticles": True,
        "comment": True,
        "manageOwnAccount": True,
        "writeArticles": is_editor,
        "manageXAgent": is_admin,
        "adminTerminal": is_admin,
        "manageUsers": is_admin,
    }


def public_user_view(user: dict[str, Any]) -> dict[str, Any]:
    role = resolve_role_for_email(str(user.get("email") or ""), str(user.get("role") or "reader"))
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "plan": user.get("plan") or ("Admin" if role == "admin" else "Reader"),
        "role": role,
        "supabase_user_id": user.get("supabase_user_id"),
        "email_confirmed": bool(user.get("email_confirmed")),
        "last_login_at": user.get("last_login_at"),
        "created_at": user.get("created_at"),
        "permissions": permissions_for_role(role),
        "is_admin": role == "admin",
    }


def sync_user_from_claims(
    claims: dict[str, Any],
    *,
    name_override: str | None = None,
    touch_login: bool = True,
) -> dict[str, Any]:
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    email = _claims_email(claims)
    if not email:
        raise HTTPException(status_code=401, detail="Authenticated token is missing an email claim")
    name = (name_override or "").strip() or _claims_name(claims, email)
    confirmed = _claims_email_confirmed(claims)
    existing = queries.get_user_by_supabase_id(subject)
    if not existing:
        existing = queries.get_user_by_email(email)
    role = resolve_role_for_email(email, (existing or {}).get("role"))
    user = queries.upsert_user(
        name=name[:120],
        email=email,
        plan="Admin" if role == "admin" else "Reader",
        supabase_user_id=subject,
        role=role,
        email_confirmed=confirmed,
        touch_login=touch_login,
    )
    # Ensure allowlisted admins stay elevated even if an older row had reader.
    if role == "admin" and str(user.get("role") or "").lower() != "admin":
        user = queries.set_user_role(int(user["id"]), "admin") or user
    return user


def require_authenticated_user(authorization: str = Header(default="")) -> dict[str, Any]:
    claims = decode_supabase_jwt(authorization)
    return sync_user_from_claims(claims, touch_login=False)


def require_admin_user(authorization: str = Header(default="")) -> dict[str, Any]:
    user = require_authenticated_user(authorization)
    view = public_user_view(user)
    if not view["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_signal_agent_token(
    x_signal_token: str = "",
    authorization: str = "",
) -> None:
    expected = (settings.signal_api_token or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Signal agent access is not configured")
    supplied = (x_signal_token or extract_bearer_token(authorization)).strip()
    if not supplied or not compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid Signal agent token")
