# Authentication & Accounts

Signal uses **Supabase Auth** as the only identity provider (email/password).
App profile data (numeric id, role, plan) lives in Postgres `users`.

Passwords are **never** stored in Signal’s database.

## Capabilities

| Feature | Status |
|---------|--------|
| Sign up / sign in | Account modal |
| Password policy (10+ chars, letter + number) | Enforced in UI |
| Email confirmation | Supabase + resend in UI |
| Forgot / reset password | Supabase email link → recover mode |
| Change password (signed in) | Account → Security |
| Update display name | Account → Profile (`PATCH /users/me`) |
| Session restore / refresh | Supabase PKCE + `onAuthStateChange` |
| Secure profile sync | `POST /users` requires JWT; email/`sub` from token |
| Current user | `GET /users/me`, `PATCH /users/me` |
| Roles | `reader` / `editor` / `admin` |
| Permissions map | Returned on every user payload |
| Admin allowlist | `SIGNAL_ADMIN_EMAILS` (default `benwealand@gmail.com`) auto-elevates to `admin` |
| Admin user directory | `GET /admin/users`, `PATCH /admin/users/{id}/role` |
| Admin X terminal | Settings (admin only) via `/admin/*` |

## Frontend env (Vercel)

```env
VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=...
VITE_SIGNAL_API_URL=https://your-backend.onrender.com
VITE_SIGNAL_ADMIN_EMAILS=benwealand@gmail.com
```

## Backend env (Render)

```env
SUPABASE_JWT_SECRET=...          # Project Settings → API → JWT Secret
SIGNAL_ADMIN_EMAILS=benwealand@gmail.com
SIGNAL_API_TOKEN=...             # agents/CI only — not for browser login
DATABASE_URL=...
CORS_ORIGINS=https://your-frontend.vercel.app
```

Apply migration `backend/app/db/migrations/0003_user_roles_auth.sql` (or recreate from `schema.sql`).

## Supabase dashboard checklist

1. Authentication → Providers → **Email** enabled
2. Confirm email (recommended for production)
3. Site URL = your Vercel URL
4. Redirect URLs include `https://your-frontend.vercel.app/**`
5. Password requirements ≥ app policy

## Role model

| Role | Powers |
|------|--------|
| `reader` | Save, comment, personal history |
| `editor` | Reserved for future desk tools (`writeArticles`) |
| `admin` | `/admin/*`, X usage terminal, manage users/roles |

Admin is granted when:

1. `users.role = 'admin'`, or
2. email is listed in `SIGNAL_ADMIN_EMAILS` (synced on login)

## API auth summary

| Caller | Mechanism |
|--------|-----------|
| Browser | `Authorization: Bearer <supabase access_token>` |
| Agents / GitHub Actions | `SIGNAL_API_TOKEN` / `X-Signal-Token` |
| `POST /users` | **JWT required** (no anonymous upsert) |
| `/admin/*` | JWT + admin role / allowlist |

## Security notes

- JWT verified with `SUPABASE_JWT_SECRET` (HS256, audience `authenticated`, requires `exp` + `sub`)
- Client cannot spoof email/`supabase_user_id` on sync — taken from token claims
- Auth endpoints rate-limited (30/min/IP on `/users`)
- CORS allowlist via `CORS_ORIGINS`
- Security headers: `nosniff`, `DENY` framing, strict referrer, `no-store` on `/users` and `/admin`
- No CSRF tokens needed for Bearer-header API calls
- Admins cannot demote themselves via `/admin/users/{id}/role`
- Anonymous likes/comments still allowed via `session_id` when `user_id` is omitted
