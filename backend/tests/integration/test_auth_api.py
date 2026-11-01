"""Sign up, log in, log out, /api/auth/me, and the session cookie."""

import logging
from datetime import timedelta

import pytest
from argon2 import PasswordHasher
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE
from app.core import security
from app.core.config import get_settings
from app.main import create_app
from app.models import User, UserSession
from app.models.base import utc_now
from app.seed import DEFAULT_CATEGORIES
from tests.conftest import ALICE, PASSWORD, sign_up

USER_FIELDS = {"id", "email", "created_at"}


def login(client: TestClient, email: str = ALICE, password: str = PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def session_cookie_header(response) -> str:
    headers = [h for h in response.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE)]
    assert len(headers) == 1, response.headers
    return headers[0]


# --- Sign up -----------------------------------------------------------------------------------


def test_signup_creates_the_account_and_signs_in(anon_client: TestClient, db: Session) -> None:
    response = anon_client.post(
        "/api/auth/signup", json={"email": "  Alice@Example.COM ", "password": PASSWORD}
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == USER_FIELDS  # never password or password_hash
    assert body["email"] == "alice@example.com"  # normalised: trimmed, lower-cased
    assert anon_client.get("/api/auth/me").json() == body  # the cookie signs the client in

    stored = db.scalars(select(User)).one()
    assert stored.password_hash.startswith("$argon2id$")
    assert PASSWORD not in stored.password_hash


def test_signup_gives_the_new_user_the_default_categories(anon_client: TestClient) -> None:
    sign_up(anon_client, ALICE)
    categories = anon_client.get("/api/categories").json()

    assert len(categories) == len(DEFAULT_CATEGORIES)
    assert all(c["is_default"] for c in categories)


@pytest.mark.parametrize("email", [ALICE, "ALICE@example.com", " alice@EXAMPLE.com "])
def test_duplicate_email_is_rejected_ignoring_case(anon_client: TestClient, email: str) -> None:
    sign_up(TestClient(anon_client.app), ALICE)

    response = anon_client.post("/api/auth/signup", json={"email": email, "password": PASSWORD})

    assert response.status_code == 409
    assert response.json() == {"detail": "An account with this email already exists"}
    assert "set-cookie" not in response.headers
    assert anon_client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"email": "not-an-email", "password": PASSWORD}, "email"),
        ({"email": ALICE, "password": "too-short"}, "password"),
        ({"email": ALICE, "password": "x" * 129}, "password"),
        ({"email": ALICE}, "password"),
    ],
)
def test_signup_validation_errors_do_not_echo_the_input(
    anon_client: TestClient, payload: dict, field: str
) -> None:
    response = anon_client.post("/api/auth/signup", json=payload)

    assert response.status_code == 422
    errors = response.json()["detail"]
    assert [e["loc"] for e in errors] == [["body", field]]
    assert all("input" not in e and "ctx" not in e for e in errors)
    if "password" in payload:
        assert payload["password"] not in response.text


def test_signup_rejects_unexpected_fields(anon_client: TestClient) -> None:
    response = anon_client.post(
        "/api/auth/signup", json={"email": ALICE, "password": PASSWORD, "is_admin": True}
    )
    assert response.status_code == 422


# --- Log in ------------------------------------------------------------------------------------


def test_login_succeeds_with_any_email_case(anon_client: TestClient) -> None:
    created = sign_up(TestClient(anon_client.app), ALICE)

    response = login(anon_client, email="ALICE@Example.com")

    assert response.status_code == 200
    assert response.json() == created
    assert anon_client.get("/api/auth/me").json() == created


@pytest.mark.parametrize(
    ("email", "password"),
    [(ALICE, "wrong password here"), ("nobody@example.com", PASSWORD), ("not an email", "x")],
)
def test_invalid_login_gives_one_generic_answer(
    anon_client: TestClient, email: str, password: str
) -> None:
    sign_up(TestClient(anon_client.app), ALICE)

    response = login(anon_client, email=email, password=password)

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}
    assert "set-cookie" not in response.headers
    assert anon_client.get("/api/auth/me").status_code == 401


def test_unknown_email_still_runs_a_password_check(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # So a failed login takes about as long whether or not the account exists.
    calls = []

    class CountingHasher(PasswordHasher):
        def verify(self, hash, password):
            calls.append(1)
            return super().verify(hash, password)

    monkeypatch.setattr(
        security, "password_hasher", CountingHasher(time_cost=1, memory_cost=8, parallelism=1)
    )

    assert login(anon_client, email="nobody@example.com").status_code == 401
    assert calls == [1]


def test_login_validation_errors_do_not_echo_the_password(anon_client: TestClient) -> None:
    response = anon_client.post("/api/auth/login", json={"email": ALICE, "password": "p" * 200})
    assert response.status_code == 422
    assert "p" * 200 not in response.text


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/x-www-form-urlencoded", "multipart/form-data"]
)
def test_login_only_accepts_json(anon_client: TestClient, content_type: str) -> None:
    # A cross-site HTML form can only send these content types; none of them is parsed as JSON.
    sign_up(TestClient(anon_client.app), ALICE)
    body = f'{{"email": "{ALICE}", "password": "{PASSWORD}"}}'

    response = anon_client.post(
        "/api/auth/login", content=body, headers={"content-type": content_type}
    )

    assert response.status_code == 422
    assert "set-cookie" not in response.headers


# --- Session cookie ----------------------------------------------------------------------------


def test_session_cookie_attributes(anon_client: TestClient) -> None:
    response = anon_client.post("/api/auth/signup", json={"email": ALICE, "password": PASSWORD})
    cookie = session_cookie_header(response)
    attributes = {part.strip().split("=")[0].lower() for part in cookie.split(";")}

    assert "httponly" in attributes
    assert "samesite=lax" in cookie.lower()
    assert "path=/" in cookie.lower()
    assert f"max-age={14 * 24 * 60 * 60}" in cookie.lower()
    assert "secure" not in attributes  # local environment: plain HTTP
    assert "domain" not in attributes  # host-only


def test_secure_cookie_when_configured(
    engine, monkeypatch: pytest.MonkeyPatch, app: FastAPI
) -> None:
    monkeypatch.setenv("SESSION_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        response = TestClient(app).post(
            "/api/auth/signup", json={"email": ALICE, "password": PASSWORD}
        )
        assert "secure" in session_cookie_header(response).lower().split("; ")
    finally:
        get_settings.cache_clear()


def test_only_a_hash_of_the_token_is_stored(anon_client: TestClient, db: Session) -> None:
    sign_up(anon_client, ALICE)
    token = anon_client.cookies[SESSION_COOKIE]
    stored = db.scalars(select(UserSession)).one()

    assert stored.token_hash == security.hash_session_token(token)
    assert token not in stored.token_hash


def test_stored_hash_is_not_a_valid_cookie(anon_client: TestClient, db: Session) -> None:
    # A leaked sessions table cannot be replayed as cookies.
    sign_up(anon_client, ALICE)
    stolen_hash = db.scalars(select(UserSession.token_hash)).one()

    attacker = TestClient(anon_client.app, cookies={SESSION_COOKIE: stolen_hash})
    assert attacker.get("/api/auth/me").status_code == 401


def test_each_login_gets_a_new_token_and_ends_the_previous_one(anon_client: TestClient) -> None:
    sign_up(anon_client, ALICE)
    first = anon_client.cookies[SESSION_COOKIE]

    assert login(anon_client).status_code == 200
    second = anon_client.cookies[SESSION_COOKIE]

    assert second != first
    replay = TestClient(anon_client.app, cookies={SESSION_COOKIE: first})
    assert replay.get("/api/auth/me").status_code == 401
    assert anon_client.get("/api/auth/me").status_code == 200


def test_sessions_on_two_devices_are_independent(app: FastAPI) -> None:
    laptop, phone = TestClient(app), TestClient(app)
    sign_up(laptop, ALICE)
    assert login(phone).status_code == 200

    assert laptop.post("/api/auth/logout").status_code == 204

    assert laptop.get("/api/auth/me").status_code == 401
    assert phone.get("/api/auth/me").status_code == 200


def test_expired_session_is_rejected_and_removed(anon_client: TestClient, db: Session) -> None:
    sign_up(anon_client, ALICE)
    session = db.scalars(select(UserSession)).one()
    session.expires_at = utc_now() - timedelta(seconds=1)
    db.commit()

    assert anon_client.get("/api/auth/me").status_code == 401
    db.expire_all()
    assert db.scalars(select(UserSession)).all() == []


@pytest.mark.parametrize("cookie", ["", "garbage", "a" * 43, "../../etc/passwd", "' OR 1=1 --"])
def test_forged_cookies_are_rejected(app: FastAPI, cookie: str) -> None:
    sign_up(TestClient(app), ALICE)
    forged = TestClient(app, cookies={SESSION_COOKIE: cookie})

    response = forged.get("/api/auth/me")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_tampered_cookie_is_rejected(anon_client: TestClient) -> None:
    sign_up(anon_client, ALICE)
    token = anon_client.cookies[SESSION_COOKIE]
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

    assert (
        TestClient(anon_client.app, cookies={SESSION_COOKIE: tampered})
        .get("/api/auth/me")
        .status_code
        == 401
    )


# --- Log out and /me ---------------------------------------------------------------------------


def test_logout_ends_the_session_and_clears_the_cookie(
    anon_client: TestClient, db: Session
) -> None:
    sign_up(anon_client, ALICE)
    token = anon_client.cookies[SESSION_COOKIE]

    response = anon_client.post("/api/auth/logout")

    assert response.status_code == 204
    cleared = session_cookie_header(response).lower()
    assert 'spendwise_session=""' in cleared or "spendwise_session=;" in cleared
    assert "max-age=0" in cleared
    assert anon_client.get("/api/auth/me").status_code == 401
    assert db.scalars(select(UserSession)).all() == []
    # A copy of the old cookie no longer works either.
    replay = TestClient(anon_client.app, cookies={SESSION_COOKIE: token})
    assert replay.get("/api/categories").status_code == 401


def test_logout_without_a_session_is_harmless(anon_client: TestClient) -> None:
    assert anon_client.post("/api/auth/logout").status_code == 204


def test_me_requires_a_session(anon_client: TestClient) -> None:
    response = anon_client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_me_returns_only_public_fields(client: TestClient) -> None:
    body = client.get("/api/auth/me").json()

    assert set(body) == USER_FIELDS
    assert body["email"] == ALICE
    assert "argon2" not in client.get("/api/auth/me").text


# --- Unauthenticated access --------------------------------------------------------------------

PUBLIC = {
    ("get", "/api/health"),
    ("get", "/api/health/ready"),
    ("post", "/api/auth/signup"),
    ("post", "/api/auth/login"),
    ("post", "/api/auth/logout"),
}


def protected_operations() -> list[tuple[str, str]]:
    spec = create_app().openapi()
    return sorted(
        (method, path)
        for path, item in spec["paths"].items()
        for method in item
        if (method, path) not in PUBLIC
    )


def test_every_data_route_is_protected() -> None:
    operations = protected_operations()
    assert len(operations) == 14  # me + 5 categories + 5 transactions + 3 analytics
    spec = create_app().openapi()
    for method, path in operations:
        assert spec["paths"][path][method]["security"] == [{"APIKeyCookie": []}], (method, path)


@pytest.mark.parametrize(("method", "path"), protected_operations())
def test_protected_routes_answer_401_without_a_session(
    anon_client: TestClient, client: TestClient, method: str, path: str
) -> None:
    # Data exists (Alice's defaults), the ids are real, and the body is empty: still 401,
    # before any validation or lookup can reveal anything.
    url = path.replace("{category_id}", "1").replace("{transaction_id}", "1")
    response = anon_client.request(method, url, json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


# --- Logging -----------------------------------------------------------------------------------


def test_passwords_never_reach_the_logs(
    anon_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "a very private passphrase 42"
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)  # log SQL and parameters
        try:
            anon_client.post("/api/auth/signup", json={"email": ALICE, "password": secret})
            login(anon_client, password=secret)
            login(anon_client, password=secret + " wrong")
            anon_client.post("/api/auth/signup", json={"email": "b@example.com", "password": "s"})
        finally:
            logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    assert caplog.records, "expected SQL logging to be captured"
    assert secret not in caplog.text
