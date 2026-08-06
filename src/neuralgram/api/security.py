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
