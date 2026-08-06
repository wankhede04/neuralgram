# Signup/Login for API Key Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user self-provision an isolated tenant + API key via `POST /auth/signup`, and rotate it via `POST /auth/login`, replacing the current requirement that a human hand-edit `.env` for every new key.

**Architecture:** A new `users` table (no RLS — it's a system identity table, not tenant data, same category as `jobs`) backs two new public endpoints under a new `routes_auth.py` router. `deps.py`'s `_resolve` gains a second lookup tier: static `.env` keys are checked first (unchanged), then a DB lookup by hashed key. Everything downstream of `require_tenant`/`require_role` (RLS, RBAC, all four AI-gateway call sites, Swagger's `x-api-key` Authorize flow) is untouched.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Alembic, `bcrypt` (new dependency) for password hashing, stdlib `hashlib`/`secrets` for API key generation/hashing (matching the existing `key_fingerprint()` pattern in `deps.py`).

## Global Constraints

- Plaintext API keys are never stored — only `sha256(key).hexdigest()` (full 64-char hex, distinct from `key_fingerprint()`'s truncated 12-char audit fingerprint).
- Login cannot re-show the original key (only its hash is stored); login issues a **new** key and invalidates the old one. This is a deliberate, user-approved tradeoff (see spec).
- No session tokens, no dashboard, no multi-key-per-user support — one user = one tenant = one active key (YAGNI, per spec's Non-goals).
- Static `.env`-based `API_KEYS`/`API_KEY_ROLES` keep working unchanged as a fallback tier — do not remove or alter existing behavior for those.
- Login/signup error messages must not leak whether an email exists (generic `401` for both "unknown email" and "wrong password").
- `mypy --strict` and `ruff` must pass on all new/modified files (existing project standard, see `pyproject.toml`).

---

## File Structure

- **Modify:** `pyproject.toml` — add `bcrypt` dependency.
- **Create:** `src/neuralgram/api/security.py` — password hashing, API key generation/hashing helpers. New file because these are auth-primitive functions used by both `routes_auth.py` and `deps.py`, and don't belong in either.
- **Modify:** `src/neuralgram/storage/models.py` — add `User` model.
- **Create:** `migrations/versions/0007_users.py` — new `users` table, no RLS.
- **Create:** `src/neuralgram/api/routes_auth.py` — `POST /auth/signup`, `POST /auth/login`.
- **Modify:** `src/neuralgram/api/deps.py` — `_resolve` becomes async, adds DB lookup tier.
- **Modify:** `src/neuralgram/api/app.py` — register the new router.
- **Create:** `tests/unit/test_api_security.py` — hashing/key-generation unit tests.
- **Create:** `tests/integration/test_api_auth_signup.py` — full signup/login flow against a real Postgres (testcontainers, mirroring `tests/integration/test_api_memory.py`'s pattern).

---

### Task 1: Password + API key hashing primitives

**Files:**
- Modify: `pyproject.toml`
- Create: `src/neuralgram/api/security.py`
- Test: `tests/unit/test_api_security.py`

**Interfaces:**
- Produces: `hash_password(password: str) -> str`, `verify_password(password: str, hashed: str) -> bool`, `generate_api_key() -> str`, `hash_api_key(api_key: str) -> str` — all consumed by Task 3 (`routes_auth.py`) and Task 4 (`deps.py`).

- [ ] **Step 1: Add the `bcrypt` dependency**

Edit `pyproject.toml`, in the `dependencies` list, add a line after `"httpx>=0.27",`:

```toml
    "bcrypt>=4.1",
```

Run: `uv sync`
Expected: installs `bcrypt` with no errors.

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/test_api_security.py`:

```python
"""Unit tests: password hashing and API key generation/hashing primitives."""

from neuralgram.api.security import (
    generate_api_key,
    hash_api_key,
    hash_password,
    verify_password,
)


def test_hash_password_round_trip() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", hashed)


def test_verify_password_rejects_wrong_password() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert not verify_password("wrong-password", hashed)


def test_hash_password_is_not_plaintext() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert "correct-horse-battery-staple" not in hashed


def test_generate_api_key_produces_unique_keys() -> None:
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100


def test_hash_api_key_is_deterministic() -> None:
    key = generate_api_key()
    assert hash_api_key(key) == hash_api_key(key)


def test_hash_api_key_differs_for_different_keys() -> None:
    assert hash_api_key(generate_api_key()) != hash_api_key(generate_api_key())


def test_hash_api_key_is_not_plaintext() -> None:
    key = generate_api_key()
    assert key not in hash_api_key(key)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_api_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'neuralgram.api.security'`

- [ ] **Step 4: Write the implementation**

Create `src/neuralgram/api/security.py`:

```python
"""Password hashing and API key generation/hashing primitives (auth, M5-2 extension).

`hash_api_key` uses full sha256 hex (64 chars) for the DB unique-key lookup —
distinct from `key_fingerprint()` in `deps.py`, which truncates to 12 chars
for audit-log display and is not used for equality lookups.
"""

import hashlib
import secrets

import bcrypt


def hash_password(password: str) -> str:
    """Bcrypt-hash a plaintext password for storage."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Check a plaintext password against a bcrypt hash from `hash_password`."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def generate_api_key() -> str:
    """Generate a new random API key, shown to the user exactly once."""
    return secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    """Full sha256 hex digest of an API key, for unique storage/lookup."""
    return hashlib.sha256(api_key.encode()).hexdigest()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_api_security.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Type-check and lint**

Run: `uv run mypy src/neuralgram/api/security.py && uv run ruff check src/neuralgram/api/security.py tests/unit/test_api_security.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/neuralgram/api/security.py tests/unit/test_api_security.py
git commit --author="wankhede04 <wankhedevijay04@gmail.com>" -m "feat(api): add password hashing and API key generation primitives"
```

---

### Task 2: `users` table (model + migration)

**Files:**
- Modify: `src/neuralgram/storage/models.py`
- Create: `migrations/versions/0007_users.py`

**Interfaces:**
- Consumes: `Base` from `storage/models.py` (existing).
- Produces: `User` model with columns `id, email, hashed_password, tenant_id, hashed_key, role, created_at` — consumed by Task 3 (`routes_auth.py`, inserts/updates rows) and Task 4 (`deps.py`, queries by `hashed_key`).

- [ ] **Step 1: Add the `User` model**

Edit `src/neuralgram/storage/models.py`. Add this class after `AuditEvent` (before `Job`):

```python
class User(Base):
    """Self-serve signup identity: one user = one tenant = one active API key.

    No RLS here — this is a system identity table (like `jobs`), not
    tenant-scoped data. Only ever queried via the system session factory,
    before a tenant context can even be established (M5-2 extension).
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    hashed_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="writer")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Write the migration**

Create `migrations/versions/0007_users.py`:

```python
"""users: self-serve signup identity, one user = one tenant = one key (M5-2 ext)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-06

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("hashed_key", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="writer"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_hashed_key", "users", ["hashed_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_hashed_key", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
```

- [ ] **Step 3: Verify the migration applies cleanly**

Run (against your local Docker Postgres from earlier in this project — adjust if your container name differs):

```bash
DATABASE_URL="postgresql+asyncpg://neuralgram:neuralgram@localhost:5432/neuralgram" uv run alembic upgrade head
```

Expected: output ends with `Running upgrade 0006 -> 0007, users: self-serve signup identity...` and no errors.

- [ ] **Step 4: Type-check**

Run: `uv run mypy src/neuralgram/storage/models.py`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/neuralgram/storage/models.py migrations/versions/0007_users.py
git commit --author="wankhede04 <wankhedevijay04@gmail.com>" -m "feat(storage): add users table for self-serve signup (0007)"
```

---

### Task 3: `/auth/signup` and `/auth/login` endpoints

**Files:**
- Create: `src/neuralgram/api/routes_auth.py`
- Modify: `src/neuralgram/api/app.py`

**Interfaces:**
- Consumes: `hash_password`, `verify_password`, `generate_api_key`, `hash_api_key` from Task 1; `User` from Task 2; `request.app.state.system_session_factory` (existing, built in `app.py`'s `_lifespan`).
- Produces: `router` (APIRouter, mounted at `/auth`) — consumed by Task 3 Step 4 (`app.py` registration). Response shape `{"api_key": str, "tenant_id": str, "role": str}` for both endpoints.

- [ ] **Step 1: Write the router**

Create `src/neuralgram/api/routes_auth.py`:

```python
"""Self-serve signup/login: API key provisioning without a human editing .env.

One user = one tenant = one active key (YAGNI — no multi-key management).
Plaintext keys are shown exactly once, at signup or login; only their hash
is ever stored. Login cannot re-show the original key (only its hash is
kept) — it issues a fresh key and invalidates the old one. This tradeoff
was deliberately chosen over reversible/encrypted storage: a DB leak under
hashing exposes no usable key material.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from neuralgram.api.security import generate_api_key, hash_api_key, hash_password, verify_password
from neuralgram.storage.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    """Signup credentials."""

    email: str
    password: str


class AuthResponse(BaseModel):
    """A freshly (re)issued API key, shown exactly once."""

    api_key: str
    tenant_id: str
    role: str


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup_endpoint(body: SignupRequest, request: Request) -> AuthResponse:
    """Create a new user + tenant + API key. Returns the plaintext key once."""
    factory = request.app.state.system_session_factory
    async with factory() as session:
        existing = await session.execute(select(User).where(User.email == body.email))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="email already registered"
            )

        api_key = generate_api_key()
        user = User(
            id=uuid.uuid4().hex,
            email=body.email,
            hashed_password=hash_password(body.password),
            tenant_id=f"user-{uuid.uuid4().hex[:12]}",
            hashed_key=hash_api_key(api_key),
            role="writer",
        )
        session.add(user)
        await session.commit()

    return AuthResponse(api_key=api_key, tenant_id=user.tenant_id, role=user.role)


@router.post("/login", response_model=AuthResponse)
async def login_endpoint(body: SignupRequest, request: Request) -> AuthResponse:
    """Verify credentials and issue a fresh API key, invalidating the previous one."""
    factory = request.app.state.system_session_factory
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
    )
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == body.email))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(body.password, user.hashed_password):
            raise invalid_credentials

        api_key = generate_api_key()
        user.hashed_key = hash_api_key(api_key)
        await session.commit()

    return AuthResponse(api_key=api_key, tenant_id=user.tenant_id, role=user.role)
```

Note: `SignupRequest` is reused as the login request body — both take `{email, password}`, no need for a second identical model (DRY).

- [ ] **Step 2: Register the router**

Edit `src/neuralgram/api/app.py`. Add the import near the other route imports:

```python
from neuralgram.api.routes_auth import router as auth_router
```

Then in `create_app`, add the registration next to the existing ones:

```python
    app.include_router(memory_router)
    app.include_router(admin_router)
    app.include_router(auth_router)
```

- [ ] **Step 3: Verify it boots and shows up in OpenAPI**

Run: `uv run python -c "from neuralgram.api.app import create_app; from neuralgram.common.config import Settings; app = create_app(Settings(_env_file=None)); print('/auth/signup' in app.openapi()['paths']); print('/auth/login' in app.openapi()['paths'])"`
Expected: `True` printed twice, no errors.

- [ ] **Step 4: Type-check and lint**

Run: `uv run mypy src/neuralgram/api/routes_auth.py src/neuralgram/api/app.py && uv run ruff check src/neuralgram/api/routes_auth.py src/neuralgram/api/app.py`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/neuralgram/api/routes_auth.py src/neuralgram/api/app.py
git commit --author="wankhede04 <wankhedevijay04@gmail.com>" -m "feat(api): add /auth/signup and /auth/login endpoints"
```

---

### Task 4: Wire DB-issued keys into `require_tenant`/`require_role`

**Files:**
- Modify: `src/neuralgram/api/deps.py`

**Interfaces:**
- Consumes: `hash_api_key` from Task 1; `User` from Task 2; `request.app.state.system_session_factory`.
- Produces: no change to `require_tenant`/`require_role`'s public signatures — callers (all existing routes, Swagger's Authorize flow) are unaffected.

- [ ] **Step 1: Write the failing test**

This test needs a real DB, so it belongs in the integration suite (Task 5), not unit — skip ahead to Task 5's Step 1 for the actual test, then come back here to make it pass. This step exists to keep the TDD order explicit: **do not write Task 4's implementation before Task 5's Step 1 test exists and fails.**

Go to Task 5, Step 1, write that test, run it, confirm it fails with a `401` (since `deps.py` doesn't check the DB yet), then return here.

- [ ] **Step 2: Rewrite `_resolve` to add the DB lookup tier**

Edit `src/neuralgram/api/deps.py`. Replace the whole file with:

```python
"""API dependencies: authentication, RBAC roles, and tenant scoping (C5/C7).

Roles (M5-2): reader < writer < admin. Two key sources, checked in order:
1. Static `Settings.api_key_roles` (env-configured, e.g. .env's my-test-key).
2. DB-issued keys from self-serve signup/login (M5-2 extension) — looked up
   by hash via the system session factory, since no tenant context exists
   yet at this point in the request.
The actor recorded in audit logs is a SHA-256 fingerprint of the key — the
raw key is never stored or logged (ADR-0006).
"""

import hashlib
import hmac

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select

from neuralgram.api.security import hash_api_key
from neuralgram.storage.models import User

_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

ROLE_LEVELS = {"reader": 0, "writer": 1, "admin": 2}
DEFAULT_ROLE = "writer"


def key_fingerprint(api_key: str) -> str:
    """Short stable identifier for an API key; safe to store and log."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


def _resolve_static(request: Request, api_key: str) -> tuple[str, str] | None:
    """Check the env-configured API_KEYS/API_KEY_ROLES dict."""
    settings = request.app.state.settings
    for configured_key, tenant_id in settings.api_keys.items():
        if hmac.compare_digest(configured_key, api_key):
            role = settings.api_key_roles.get(configured_key, DEFAULT_ROLE)
            return str(tenant_id), role
    return None


async def _resolve_db(request: Request, api_key: str) -> tuple[str, str] | None:
    """Check DB-issued keys from self-serve signup/login.

    Skips gracefully if the app's lifespan never ran (e.g. bare unit tests
    that construct a TestClient without the `with` context manager) --
    system_session_factory won't exist yet in that case, and there is no
    DB-issued key to find regardless.
    """
    factory = getattr(request.app.state, "system_session_factory", None)
    if factory is None:
        return None
    hashed = hash_api_key(api_key)
    async with factory() as session:
        result = await session.execute(select(User).where(User.hashed_key == hashed))
        user = result.scalar_one_or_none()
    if user is None:
        return None
    return user.tenant_id, user.role


async def _resolve(request: Request, api_key: str | None) -> tuple[str, str] | None:
    """Return (tenant_id, role) for a valid key, else None."""
    if not api_key:
        return None
    return _resolve_static(request, api_key) or await _resolve_db(request, api_key)


async def require_tenant(request: Request, api_key: str | None = Security(_api_key_header)) -> str:
    """Resolve the calling tenant from the `x-api-key` header (any role).

    Stores tenant/role/actor on `request.state` for RBAC checks and audit.
    Raises 401 when the key is missing or unknown; keys are never logged.
    """
    resolved = await _resolve(request, api_key)
    if resolved is None:
        request.state.audit_actor = "invalid-key"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing API key"
        )
    tenant_id, role = resolved
    request.state.tenant_id = tenant_id
    request.state.role = role
    request.state.audit_actor = key_fingerprint(api_key or "")
    return tenant_id


def require_role(minimum: str) -> object:
    """Dependency factory: the caller's role must be at least `minimum`."""

    async def _check(request: Request, api_key: str | None = Security(_api_key_header)) -> str:
        tenant_id = await require_tenant(request, api_key)
        role = request.state.role
        if ROLE_LEVELS[role] < ROLE_LEVELS[minimum]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {role!r} may not perform this action (needs {minimum!r})",
            )
        return tenant_id

    return _check
```

- [ ] **Step 3: Run the existing auth unit tests to confirm no regression**

Run: `uv run pytest tests/unit/test_api_auth.py -v`
Expected: PASS (all 4 existing tests) — these use a bare `TestClient(...)` without `with`, so `system_session_factory` is absent and `_resolve_db` returns `None` immediately, preserving prior behavior exactly.

- [ ] **Step 4: Type-check and lint**

Run: `uv run mypy src/neuralgram/api/deps.py && uv run ruff check src/neuralgram/api/deps.py`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add src/neuralgram/api/deps.py
git commit --author="wankhede04 <wankhedevijay04@gmail.com>" -m "feat(api): resolve DB-issued keys in require_tenant/require_role"
```

---

### Task 5: Integration tests — full signup/login flow against real Postgres

**Files:**
- Create: `tests/integration/test_api_auth_signup.py`

**Interfaces:**
- Consumes: `create_app` and `Settings` (existing, same pattern as `tests/integration/test_api_memory.py`).

- [ ] **Step 1: Write the test file**

Create `tests/integration/test_api_auth_signup.py`:

```python
"""Integration: self-serve signup/login end-to-end against real Postgres."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from neuralgram.api.app import create_app
from neuralgram.common.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> Iterator[TestClient]:
    with PostgresContainer("pgvector/pgvector:pg16") as container:
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=REPO_ROOT,
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr

        settings = Settings(
            _env_file=None,
            database_url=url,
            vault_path=str(tmp_path_factory.mktemp("vault")),
        )
        with TestClient(create_app(settings)) as test_client:
            yield test_client


def test_signup_returns_usable_key(client: TestClient) -> None:
    response = client.post(
        "/auth/signup", json={"email": "alice@example.com", "password": "hunter2pass"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["role"] == "writer"
    assert body["tenant_id"].startswith("user-")

    search = client.get(
        "/memory/search", params={"q": "x"}, headers={"x-api-key": body["api_key"]}
    )
    assert search.status_code == 200, search.text


def test_duplicate_signup_email_is_409(client: TestClient) -> None:
    client.post("/auth/signup", json={"email": "bob@example.com", "password": "pw12345678"})
    response = client.post(
        "/auth/signup", json={"email": "bob@example.com", "password": "different-pw"}
    )
    assert response.status_code == 409


def test_login_wrong_password_is_401(client: TestClient) -> None:
    client.post("/auth/signup", json={"email": "carol@example.com", "password": "correct-pw"})
    response = client.post(
        "/auth/login", json={"email": "carol@example.com", "password": "wrong-pw"}
    )
    assert response.status_code == 401


def test_login_unknown_email_is_401(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever123"}
    )
    assert response.status_code == 401


def test_login_issues_new_key_and_invalidates_old(client: TestClient) -> None:
    signup = client.post(
        "/auth/signup", json={"email": "dave@example.com", "password": "original-pw"}
    )
    old_key = signup.json()["api_key"]

    login = client.post(
        "/auth/login", json={"email": "dave@example.com", "password": "original-pw"}
    )
    assert login.status_code == 200, login.text
    new_key = login.json()["api_key"]
    assert new_key != old_key

    old_key_check = client.get(
        "/memory/search", params={"q": "x"}, headers={"x-api-key": old_key}
    )
    assert old_key_check.status_code == 401

    new_key_check = client.get(
        "/memory/search", params={"q": "x"}, headers={"x-api-key": new_key}
    )
    assert new_key_check.status_code == 200, new_key_check.text
```

- [ ] **Step 2: Run and confirm the whole flow passes**

Run: `uv run pytest tests/integration/test_api_auth_signup.py -v`
Expected: PASS (5 tests). Requires Docker running locally (testcontainers spins up a real Postgres, same as the existing `test_api_memory.py` integration suite).

If any test fails at this point, that's the signal to go back to Task 4 Step 2 and fix the implementation — do not move on with a failing integration test.

- [ ] **Step 3: Run the full test suite to confirm no regressions anywhere**

Run: `uv run pytest -v`
Expected: PASS, all tests (unit + integration + existing).

- [ ] **Step 4: Type-check and lint the whole project**

Run: `uv run mypy src && uv run ruff check src tests`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_api_auth_signup.py
git commit --author="wankhede04 <wankhedevijay04@gmail.com>" -m "test(api): integration coverage for signup/login flow"
```

---

## Manual verification (Swagger)

After all tasks are committed, restart the Docker stack and confirm in Swagger UI (`http://localhost:8000/docs`):

1. `POST /auth/signup` with a fresh email → returns `201` with an `api_key`.
2. Click **Authorize**, paste that `api_key` into `x-api-key`.
3. Call `GET /memory/search?q=test&mode=keyword` → `200` (proves the DB-issued key works end-to-end, not just in tests).
4. `POST /auth/login` with the same email/password → returns a **different** `api_key`.
5. Re-authorize with the OLD key from step 2 → any protected call now returns `401` (proves rotation works).
6. Confirm `my-test-key` (the static `.env` key) still works throughout — proves the static tier is untouched.
