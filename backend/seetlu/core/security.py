"""Token hashing (argon2id) for claim tokens, device tokens and OTP codes (docs/09-security-privacy.md)."""

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()  # argon2id with library defaults


def hash_token(token: str) -> str:
    return _hasher.hash(token)


def verify_token(token_hash: str, token: str) -> bool:
    try:
        return _hasher.verify(token_hash, token)
    except (VerificationError, InvalidHashError):
        return False


def new_device_token() -> str:
    """32 random bytes, URL-safe."""
    return secrets.token_urlsafe(32)
