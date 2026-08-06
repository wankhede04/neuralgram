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
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from neuralgram.api.deps import key_fingerprint
from neuralgram.api.security import generate_api_key, hash_api_key, hash_password, verify_password
from neuralgram.storage.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupRequest(BaseModel):
    """Signup credentials.

    `password` is bounded at 72 bytes because bcrypt raises above that —
    Field turns what would be a 500 into a clean 422.
    """

    email: str
    password: str = Field(min_length=8, max_length=72)


class AuthResponse(BaseModel):
    """A freshly (re)issued API key, shown exactly once."""

    api_key: str
    tenant_id: str
    role: str


async def _find_by_email(session: AsyncSession, email: str) -> User | None:
    """The user registered under `email`, if any."""
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup_endpoint(body: SignupRequest, request: Request) -> AuthResponse:
    """Create a new user + tenant + API key. Returns the plaintext key once."""
    factory = request.app.state.system_session_factory
    email_taken = HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="email already registered"
    )
    async with factory() as session:
        if await _find_by_email(session, body.email) is not None:
            raise email_taken

        api_key = generate_api_key()
        user = User(
            id=uuid.uuid4().hex,
            email=body.email,
            hashed_password=hash_password(body.password),
            tenant_id=f"user-{uuid.uuid4().hex}",
            hashed_key=hash_api_key(api_key),
            role="writer",
        )
        session.add(user)
        try:
            await session.commit()
        except IntegrityError:
            # Concurrent signup with the same email won the race.
            await session.rollback()
            raise email_taken from None

    request.state.tenant_id = user.tenant_id
    request.state.audit_actor = key_fingerprint(api_key)
    return AuthResponse(api_key=api_key, tenant_id=user.tenant_id, role=user.role)


@router.post("/login", response_model=AuthResponse)
async def login_endpoint(body: SignupRequest, request: Request) -> AuthResponse:
    """Verify credentials and issue a fresh API key, invalidating the previous one."""
    factory = request.app.state.system_session_factory
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
    )
    async with factory() as session:
        user = await _find_by_email(session, body.email)
        if user is None or not verify_password(body.password, user.hashed_password):
            raise invalid_credentials

        api_key = generate_api_key()
        user.hashed_key = hash_api_key(api_key)
        await session.commit()

    request.state.tenant_id = user.tenant_id
    request.state.audit_actor = key_fingerprint(api_key)
    return AuthResponse(api_key=api_key, tenant_id=user.tenant_id, role=user.role)
