"""Sign up, log in, session cookie, /api/auth/me and log out, over real HTTP."""

from integration.conftest import COOKIE_NAME as COOKIE
from integration.conftest import User, unique_email


def test_signup_signs_in_and_returns_only_public_fields(http) -> None:
    client = http()
    email = unique_email("signup")

    response = client.post(
        "/api/auth/signup", json={"email": email.upper(), "password": "integration passphrase"}
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "email", "created_at"}
    assert body["email"] == email  # stored lower-cased

    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=")
    attributes = [part.strip().lower() for part in cookie.split(";")]
    assert "httponly" in attributes
    assert "samesite=lax" in attributes
    assert "path=/" in attributes
    assert "secure" not in attributes  # the Compose stack is plain HTTP on localhost

    assert client.get("/api/auth/me").json() == body


def test_https_through_a_proxy_gets_a_secure_cookie(http) -> None:
    # Hosts such as Railway terminate TLS and forward the request with X-Forwarded-Proto: https.
    # The stack is configured for plain HTTP (SESSION_COOKIE_SECURE=false), yet the cookie must
    # be Secure, so a local setting cannot weaken a public HTTPS deployment.
    response = http().post(
        "/api/auth/signup",
        json={"email": unique_email("https"), "password": "integration passphrase"},
        headers={"X-Forwarded-Proto": "https"},
    )

    assert response.status_code == 201
    attributes = [part.strip().lower() for part in response.headers["set-cookie"].split(";")]
    assert "secure" in attributes
    assert "httponly" in attributes
    assert "samesite=lax" in attributes


def test_duplicate_email_is_rejected(alice: User, http) -> None:
    response = http().post(
        "/api/auth/signup", json={"email": alice.email.upper(), "password": "another passphrase"}
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "An account with this email already exists"}


def test_weak_password_is_rejected_without_echoing_it(http) -> None:
    response = http().post(
        "/api/auth/signup", json={"email": unique_email("weak"), "password": "too-short"}
    )

    assert response.status_code == 422
    assert "too-short" not in response.text


def test_login_session_persists_across_requests(alice: User, http) -> None:
    client = http()  # a second browser
    response = client.post(
        "/api/auth/login", json={"email": alice.email, "password": alice.password}
    )

    assert response.status_code == 200
    assert response.json()["email"] == alice.email
    for _ in range(3):
        assert client.get("/api/auth/me").json()["email"] == alice.email
        assert client.get("/api/categories").status_code == 200


def test_invalid_logins_get_one_generic_answer(alice: User, http) -> None:
    for email, password in [
        (alice.email, "wrong password entirely"),
        (unique_email("nobody"), alice.password),
    ]:
        response = http().post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid email or password"}
        assert "set-cookie" not in response.headers


def test_me_without_a_session(http) -> None:
    response = http().get("/api/auth/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


def test_logout_ends_the_session_everywhere_it_was_copied(alice: User, http) -> None:
    token = alice.client.cookies[COOKIE]

    response = alice.post("/api/auth/logout")

    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert alice.get("/api/auth/me").status_code == 401
    copied = http(cookies={COOKIE: token})
    assert copied.get("/api/auth/me").status_code == 401
    assert copied.get("/api/transactions").status_code == 401


def test_logging_out_one_browser_keeps_the_other(alice: User, http) -> None:
    phone = http()
    assert (
        phone.post(
            "/api/auth/login", json={"email": alice.email, "password": alice.password}
        ).status_code
        == 200
    )

    assert alice.post("/api/auth/logout").status_code == 204

    assert phone.get("/api/auth/me").status_code == 200


def test_forged_cookie_is_rejected(http) -> None:
    forged = http(cookies={COOKIE: "x" * 43})

    assert forged.get("/api/auth/me").status_code == 401
