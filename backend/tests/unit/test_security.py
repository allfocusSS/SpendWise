"""Password hashing and session tokens (app.core.security)."""

import hashlib

import pytest
from argon2 import PasswordHasher, Type

from app.core import security
from app.core.config import Settings

PASSWORD = "correct horse battery staple"


def test_hash_is_argon2id_and_never_the_password() -> None:
    hashed = security.hash_password(PASSWORD)

    assert hashed.startswith("$argon2id$")
    assert PASSWORD not in hashed


def test_each_hash_has_its_own_salt() -> None:
    assert security.hash_password(PASSWORD) != security.hash_password(PASSWORD)


def test_verify_accepts_only_the_right_password() -> None:
    hashed = security.hash_password(PASSWORD)

    assert security.verify_password(hashed, PASSWORD) is True
    assert security.verify_password(hashed, PASSWORD + " ") is False
    assert security.verify_password(hashed, PASSWORD.upper()) is False
    assert security.verify_password(hashed, "") is False


@pytest.mark.parametrize("bad_hash", ["", "plaintext", "$argon2id$garbage", "$2b$12$bcrypt"])
def test_verify_rejects_malformed_hashes_without_raising(bad_hash: str) -> None:
    assert security.verify_password(bad_hash, PASSWORD) is False


def test_production_parameters_are_the_rfc_9106_low_memory_profile() -> None:
    # The test suite swaps in a cheap hasher (conftest); the real module default is this one.
    default = PasswordHasher()
    assert default.type is Type.ID
    assert default.memory_cost == 65536  # KiB = 64 MiB
    assert default.time_cost == 3
    assert default.parallelism == 4


def test_hashes_made_with_weaker_parameters_need_rehashing(monkeypatch) -> None:
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    monkeypatch.setattr(security, "password_hasher", PasswordHasher())

    assert security.needs_rehash(weak) is True
    assert security.needs_rehash(security.hash_password(PASSWORD)) is False


def test_session_tokens_are_random_and_stored_only_as_sha256() -> None:
    tokens = {security.new_session_token() for _ in range(100)}
    assert len(tokens) == 100
    token = tokens.pop()
    assert len(token) >= 43  # 32 random bytes, base64url

    stored = security.hash_session_token(token)
    assert stored == hashlib.sha256(token.encode()).hexdigest()
    assert token not in stored


PRODUCTION = {"environment": "production", "database_url": "postgresql://u:p@h/d"}


def settings(monkeypatch, **values) -> Settings:
    for var in ("ENVIRONMENT", "DATABASE_URL", "SESSION_COOKIE_SECURE"):
        monkeypatch.delenv(var, raising=False)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("values", "secure"),
    [
        ({}, False),
        ({"environment": "local"}, False),
        (PRODUCTION, True),
        ({**PRODUCTION, "session_cookie_secure": "false"}, False),  # production on http://localhost
        ({"environment": "local", "session_cookie_secure": "true"}, True),
        ({"environment": "local", "session_cookie_secure": ""}, False),
    ],
)
def test_plain_http_cookie_follows_the_environment(monkeypatch, values: dict, secure: bool) -> None:
    assert settings(monkeypatch, **values).secure_cookie(request_is_https=False) is secure


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"environment": "local", "session_cookie_secure": "false"},
        {**PRODUCTION, "session_cookie_secure": "false"},  # e.g. a local setting copied to a host
        PRODUCTION,
    ],
)
def test_https_requests_always_get_a_secure_cookie(monkeypatch, values: dict) -> None:
    assert settings(monkeypatch, **values).secure_cookie(request_is_https=True) is True
