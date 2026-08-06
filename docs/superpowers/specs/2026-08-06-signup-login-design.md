# Signup/Login for API Key Provisioning

## Problem

API keys today live in a static `API_KEYS`/`API_KEY_ROLES` JSON dict, sourced
from `.env` (`src/neuralgram/api/deps.py::_resolve`). Every new user/tenant
requires a human to hand-edit `.env` and restart the process. This doesn't
scale past a handful of manually provisioned test keys, and it's a blocker
for any self-serve product surface (e.g. a Product Hunt launch).

## Goal

Let a user self-provision an isolated tenant + API key via `POST /auth/signup`,
and re-provision (rotate) via `POST /auth/login`, with zero changes to how
the rest of the app consumes a key (RLS, RBAC, Swagger's `x-api-key` flow,
the four AI-gateway call sites all stay untouched).

## Non-goals

- No session tokens / JWTs / dashboard UI. One token type: the `x-api-key`
  bearer key, exactly as today.
- No multiple keys per user, no key management (list/revoke) endpoints.
  One user = one tenant = one active key. Multi-key support is a future
  extension if ever needed, not built now (YAGNI).
- The existing static `API_KEYS`/`API_KEY_ROLES` env-based keys are **not**
  removed — they keep working as a fallback, so `my-test-key` and any
  future manually-provisioned admin/test keys are unaffected.

## Data model

New table, new migration (next in sequence after `0006_audit_events`):

```
users:
  id               varchar, primary key (uuid4 hex)
  email            varchar, unique, not null
  hashed_password  varchar, not null      -- bcrypt
  tenant_id        varchar, not null      -- generated at signup, e.g. "user-<id>"
  hashed_key       varchar, unique, not null  -- sha256(api_key), same fingerprint
                                                -- pattern as key_fingerprint() in deps.py
  role             varchar, not null, default 'writer'
  created_at       timestamptz, not null
```

The plaintext API key is **never stored** — only its hash. This means it can
only ever be shown to the user once, at the moment it's generated (signup or
login), same convention as GitHub personal access tokens.

## Endpoints

### `POST /auth/signup`
Request: `{"email": str, "password": str}`

1. `409 Conflict` if email already registered.
2. Hash password (bcrypt).
3. Generate a new API key (`secrets.token_urlsafe(32)`), hash it (sha256,
   matching `key_fingerprint()`'s algorithm in `deps.py`).
4. Generate `tenant_id` (e.g. `f"user-{uuid4().hex[:12]}"`).
5. Insert the row with `role="writer"` default.
6. Return `{"api_key": <plaintext, shown once>, "tenant_id": ..., "role": "writer"}`.

### `POST /auth/login`
Request: `{"email": str, "password": str}`

1. `401 Unauthorized` (generic message — don't leak whether the email exists)
   if email not found or password doesn't verify.
2. On success: generate a **new** API key, hash it, `UPDATE users SET
   hashed_key = ...`. This invalidates the previous key.
3. Return `{"api_key": <new plaintext, shown once>, "tenant_id": ..., "role": ...}`.

**Explicit tradeoff, confirmed with the user**: because keys are stored
hashed (not encrypted/reversible), login cannot re-show the original key —
it issues a fresh one, rotating out the old. This was chosen deliberately
over reversible (encrypted) storage: a DB leak under the hash approach
exposes no usable key material, which outweighs the UX cost of rotation on
every login. Users who lose their key need to log in again to get a new one.

## Auth rewire (`deps.py`)

`_resolve()` currently loops over `settings.api_keys` (a static dict). It
becomes an async lookup with two tiers, checked in order:

1. Static `settings.api_keys`/`settings.api_key_roles` (unchanged, for
   manually-provisioned keys like `my-test-key`).
2. New: hash the incoming key, query `users` by `hashed_key`. If found,
   return `(tenant_id, role)` from that row.

`require_tenant`/`require_role` (both already `async def` FastAPI
dependencies) gain a `db_session` (or session factory) dependency to run
this query. No change to their public signature/behavior from the caller's
perspective — Swagger's `Authorize` dialog keeps working exactly as-is.

## Error handling

- Signup, duplicate email → `409`, body `{"detail": "email already registered"}`
- Login, unknown email or wrong password → `401`, generic
  `{"detail": "invalid email or password"}` (identical for both cases,
  to avoid user enumeration)
- Malformed request body → existing FastAPI `422` validation (free, no
  new code)

## Testing

- Unit: password hash/verify round-trip; key generation produces unique,
  sufficiently random tokens; hashing is deterministic (same key → same hash).
- Integration: signup → returned key works on a protected endpoint (e.g.
  `GET /memory/search` with `mode=keyword`) → login → old key now `401`s →
  new key works.
- Negative: duplicate signup email → `409`; wrong password → `401`; using
  someone else's returned tenant_id in a request under your own key still
  respects RLS (should be impossible by construction, but worth an explicit
  test given ADR-0014's isolation guarantees).

## Out of scope for this spec (explicitly deferred)

- Rate limiting on `/auth/signup` (prevents someone scripting unlimited
  tenant creation) — flagged as a separate, already-known launch blocker
  from earlier discussion, not re-solved here.
- Email verification — signups are unverified; anyone can sign up with any
  email string. Acceptable for a self-serve demo; would need reconsidering
  before treating email as a trusted identifier for anything sensitive.
