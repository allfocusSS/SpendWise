"""Password hashing and session tokens. Nothing here logs or returns a password.

Passwords are hashed with Argon2id (argon2-cffi, RFC 9106 low-memory profile: 64 MiB, 3
passes, 4 lanes), each with its own random salt. Session tokens are 32 random bytes; only their
SHA-256 is stored, so a leaked sessions table cannot be replayed as cookies.
"""

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Module-level so tests can swap in cheaper parameters (see tests/conftest.py).
password_hasher = PasswordHasher()

# Verified against when the email is unknown, so a failed login takes about as long whether or
# not the account exists. Created on first use, with the hasher's current parameters.
_dummy_hash: str | None = None


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when the hash was made with older, weaker parameters than the current ones."""
    return password_hasher.check_needs_rehash(password_hash)


def burn_password_check(password: str) -> None:
    """Spend the same effort as a real verification, for unknown emails."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = password_hasher.hash(secrets.token_urlsafe(16))
    verify_password(_dummy_hash, password)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
