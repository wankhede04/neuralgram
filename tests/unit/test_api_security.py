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
