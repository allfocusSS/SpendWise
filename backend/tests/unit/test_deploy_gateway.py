"""The deploy gateway (deploy/aws/gateway/spendwise_deploy_gateway.py): token checks and deploys.

Everything runs locally: the GitHub issuer is replaced by a fake one (https://issuer.test) whose
discovery document and JWKS hold RSA keys generated here, and the deploy wrapper by small
scripts. Nothing talks to GitHub or AWS.
"""

import base64
import hashlib
import http.client
import importlib.util
import json
import logging
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import RSAAlgorithm

ROOT = Path(__file__).resolve().parents[3]
GATEWAY_DIR = ROOT / "deploy" / "aws" / "gateway"

_spec = importlib.util.spec_from_file_location(
    "spendwise_deploy_gateway", GATEWAY_DIR / "spendwise_deploy_gateway.py"
)
gw = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = gw
_spec.loader.exec_module(gw)

ISSUER = "https://issuer.test"
AUDIENCE = "spendwise-deploy"
REPOSITORY = "allfocusSS/SpendWise"
SUBJECT = "repo:allfocusSS@189591398/SpendWise@1441102769:ref:refs/heads/main"
WORKFLOW_REF = "allfocusSS/SpendWise/.github/workflows/ci.yml@refs/heads/main"
SHA = "835f9e36979e446878df74d9c9340bbd3ad46922"
OTHER_SHA = "1a87352a1a87352a1a87352a1a87352a1a87352a"


def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY_A, KEY_B, ATTACKER_KEY = rsa_key(), rsa_key(), rsa_key()


def jwk(private_key, kid: str, **extra) -> dict:
    data = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    return data | {"kid": kid, "alg": "RS256", "use": "sig"} | extra


class FakeIssuer:
    """Discovery and JWKS documents, served to GitHubKeys instead of the network."""

    def __init__(self, keys: list[dict]) -> None:
        self.discovery = {
            "issuer": ISSUER,
            "jwks_uri": f"{ISSUER}/.well-known/jwks",
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        self.jwks = {"keys": keys}
        self.fetches: list[str] = []
        self.fail = False

    def fetch(self, url: str):
        self.fetches.append(url)
        if self.fail:
            raise gw.KeysUnavailable("network down")
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return json.loads(json.dumps(self.discovery))
        if url == self.discovery["jwks_uri"]:
            return json.loads(json.dumps(self.jwks))
        raise gw.KeysUnavailable(f"unexpected URL {url}")


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def issuer() -> FakeIssuer:
    return FakeIssuer([jwk(KEY_A, "key-a")])


@pytest.fixture
def settings(tmp_path) -> "gw.Settings":
    return gw.Settings(
        audience=AUDIENCE,
        repository=REPOSITORY,
        repository_id="1441102769",
        owner_id="189591398",
        ref="refs/heads/main",
        workflow=".github/workflows/ci.yml",
        socket_path=tmp_path / "gateway.sock",
        state_dir=tmp_path,
        health_url="https://example.test/api/health/ready",
        issuer=ISSUER,
    )


@pytest.fixture
def keys_clock() -> Clock:
    return Clock()


@pytest.fixture
def keys(issuer, keys_clock) -> "gw.GitHubKeys":
    return gw.GitHubKeys(ISSUER, fetch=issuer.fetch, clock=keys_clock)


@pytest.fixture
def verifier(settings, keys) -> "gw.TokenVerifier":
    return gw.TokenVerifier(settings, keys)


def claims(**overrides) -> dict:
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "exp": now + 300,
        "nbf": now - 5,
        "iat": now,
        "jti": str(uuid.uuid4()),
        "repository": REPOSITORY,
        "repository_id": "1441102769",
        "repository_owner": "allfocusSS",
        "repository_owner_id": "189591398",
        "ref": "refs/heads/main",
        "ref_type": "branch",
        "event_name": "push",
        "runner_environment": "github-hosted",
        "workflow_ref": WORKFLOW_REF,
        "sha": SHA,
        "run_id": "123456789",
        "run_attempt": "1",
    }
    for name, value in overrides.items():
        if value is None:
            base.pop(name, None)
        else:
            base[name] = value
    return base


def sign(payload: dict, key=KEY_A, kid: str = "key-a", alg: str = "RS256") -> str:
    return jwt.encode(payload, key, algorithm=alg, headers={"kid": kid})


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unsigned(header: dict, payload: dict, signature: bytes = b"") -> str:
    return ".".join(
        [b64(json.dumps(header).encode()), b64(json.dumps(payload).encode()), b64(signature)]
    )


REQUEST = gw.DeployRequest(SHA, "123456789", "1")


def rejected(verifier, token: str, request=REQUEST) -> bool:
    try:
        verifier.verify(token, request)
    except gw.TokenRejected:
        return True
    return False


# --- Signature, algorithm and key ----------------------------------------------------------


def test_a_valid_github_token_is_accepted(verifier) -> None:
    payload = claims()
    assert verifier.verify(sign(payload), REQUEST) == payload


def test_a_token_signed_with_another_key_is_rejected(verifier) -> None:
    assert rejected(verifier, sign(claims(), key=ATTACKER_KEY, kid="key-a"))


def test_a_tampered_token_is_rejected(verifier) -> None:
    header, payload, signature = sign(claims()).split(".")
    forged = b64(json.dumps(claims(sha=OTHER_SHA)).encode())
    assert rejected(
        verifier, f"{header}.{forged}.{signature}", gw.DeployRequest(OTHER_SHA, "123456789", "1")
    )
    # A corrupted signature, too.
    flipped = ("A" if signature[0] != "A" else "B") + signature[1:]
    assert rejected(verifier, f"{header}.{payload}.{flipped}")


def test_an_unknown_key_id_is_rejected_after_one_refresh(verifier, issuer) -> None:
    assert not rejected(verifier, sign(claims()))
    fetched = len(issuer.fetches)
    assert rejected(verifier, sign(claims(), key=ATTACKER_KEY, kid="attacker"))
    assert len(issuer.fetches) == fetched  # within a minute of the last fetch: no refresh


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: unsigned({"alg": "none", "kid": "key-a"}, claims()), id="none"),
        pytest.param(lambda: unsigned({"alg": "None", "kid": "key-a"}, claims()), id="None"),
        pytest.param(lambda: unsigned({"kid": "key-a"}, claims()), id="no-alg"),
        pytest.param(lambda: sign(claims(), key="shared-secret", alg="HS256"), id="HS256"),
        pytest.param(lambda: sign(claims(), key="shared-secret", alg="HS512"), id="HS512"),
        # The classic confusion attack: HMAC "signed" with the RSA public key as the secret.
        pytest.param(
            lambda: unsigned(
                {"alg": "HS256", "kid": "key-a", "typ": "JWT"},
                claims(),
                hashlib.sha256(
                    KEY_A.public_key().public_bytes(
                        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
                    )
                ).digest(),
            ),
            id="HS256-with-public-key",
        ),
        pytest.param(lambda: sign(claims(), alg="RS512"), id="RS512"),
        pytest.param(lambda: sign(claims(), alg="PS256"), id="PS256"),
        pytest.param(
            lambda: sign(claims(), key=ec.generate_private_key(ec.SECP256R1()), alg="ES256"),
            id="ES256",
        ),
    ],
)
def test_only_rs256_is_accepted(verifier, token) -> None:
    assert rejected(verifier, token())


@pytest.mark.parametrize("value", ["", "not-a-token", "a.b", "a.b.c", "x" * (gw.MAX_TOKEN + 1)])
def test_malformed_tokens_are_rejected(verifier, value) -> None:
    assert rejected(verifier, value)


def test_a_token_without_a_key_id_is_rejected(verifier) -> None:
    assert rejected(verifier, jwt.encode(claims(), KEY_A, algorithm="RS256"))


# --- Issuer, audience and time -------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"iss": "https://token.actions.githubusercontent.com.evil.test"}, id="issuer"),
        pytest.param({"iss": ISSUER + "/"}, id="issuer-trailing-slash"),
        pytest.param({"aud": "sts.amazonaws.com"}, id="audience"),
        pytest.param({"aud": [AUDIENCE, "other"]}, id="audience-list"),
        pytest.param({"aud": [AUDIENCE]}, id="audience-in-a-list"),
        pytest.param({"exp": int(time.time()) - 120}, id="expired"),
        pytest.param({"nbf": int(time.time()) + 300}, id="not-yet-valid"),
        pytest.param({"iat": int(time.time()) + 300}, id="issued-in-the-future"),
        pytest.param({"iat": int(time.time()) - 3600}, id="issued-an-hour-ago"),
        pytest.param({"exp": None}, id="no-exp"),
        pytest.param({"nbf": None}, id="no-nbf"),
        pytest.param({"iat": None}, id="no-iat"),
        pytest.param({"jti": None}, id="no-jti"),
        pytest.param({"jti": ""}, id="empty-jti"),
        pytest.param({"jti": "x" * 300}, id="huge-jti"),
    ],
)
def test_issuer_audience_lifetime_and_jti_are_checked(verifier, overrides) -> None:
    assert rejected(verifier, sign(claims(**overrides)))


def test_small_clock_skew_is_tolerated(verifier) -> None:
    now = int(time.time())
    assert not rejected(verifier, sign(claims(iat=now + 30, nbf=now + 30)))


# --- GitHub claims -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        # GitHub's older, mutable subject format (no owner and repository IDs).
        pytest.param(
            {"sub": "repo:allfocusSS/SpendWise:ref:refs/heads/main"}, id="mutable-subject"
        ),
        pytest.param(
            {"sub": "repo:allfocusSS@189591398/SpendWise@1441102769:ref:refs/heads/dev"},
            id="subject-branch",
        ),
        pytest.param(
            {"sub": "repo:allfocusSS@189591398/SpendWise@1441102769:pull_request"},
            id="subject-pull-request",
        ),
        pytest.param(
            {"sub": "repo:allfocusSS@189591398/SpendWise@1441102769:environment:production"},
            id="subject-environment",
        ),
        pytest.param({"repository": "someone/SpendWise"}, id="repository"),
        pytest.param({"repository_id": "1441102770"}, id="repository-id"),
        pytest.param({"repository_id": 1441102769}, id="repository-id-as-number"),
        pytest.param({"repository_owner_id": "1"}, id="owner-id"),
        pytest.param({"ref": "refs/heads/feature"}, id="branch"),
        pytest.param({"ref": "refs/tags/v1.0.0", "ref_type": "tag"}, id="tag"),
        pytest.param({"ref_type": "tag"}, id="ref-type"),
        pytest.param({"ref": "refs/pull/42/merge"}, id="pull-request-ref"),
        pytest.param({"event_name": "pull_request"}, id="pull-request"),
        pytest.param({"event_name": "pull_request_target"}, id="pull-request-target"),
        pytest.param({"event_name": "workflow_dispatch"}, id="workflow-dispatch"),
        pytest.param({"runner_environment": "self-hosted"}, id="self-hosted-runner"),
        pytest.param({"runner_environment": None}, id="no-runner-environment"),
        pytest.param(
            {"workflow_ref": "allfocusSS/SpendWise/.github/workflows/evil.yml@refs/heads/main"},
            id="other-workflow",
        ),
        pytest.param(
            {"workflow_ref": "allfocusSS/SpendWise/.github/workflows/ci.yml@refs/pull/42/merge"},
            id="workflow-from-a-pull-request",
        ),
        pytest.param({"workflow_ref": None}, id="no-workflow-ref"),
        pytest.param({"sha": OTHER_SHA}, id="sha-does-not-match-the-body"),
        pytest.param({"run_id": "987654321"}, id="run-id-does-not-match"),
        pytest.param({"run_attempt": "2"}, id="run-attempt-does-not-match"),
    ],
)
def test_every_github_claim_must_match(verifier, overrides) -> None:
    assert rejected(verifier, sign(claims(**overrides)))


def test_repository_name_alone_is_not_enough(verifier) -> None:
    # Right name, but a re-created repository (new ID) with a matching-looking subject.
    token = sign(
        claims(
            repository_id="999",
            sub="repo:allfocusSS@189591398/SpendWise@999:ref:refs/heads/main",
        )
    )
    assert rejected(verifier, token)


def test_the_subject_comes_from_the_configured_ids(settings) -> None:
    assert settings.subject == SUBJECT
    assert settings.workflow_ref == WORKFLOW_REF


# --- Deploy request body -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"sha": "main", "run_id": "1", "run_attempt": "1"}, "invalid_sha"),
        ({"sha": SHA.upper(), "run_id": "1", "run_attempt": "1"}, "invalid_sha"),
        ({"sha": SHA[:39], "run_id": "1", "run_attempt": "1"}, "invalid_sha"),
        ({"sha": SHA + "0", "run_id": "1", "run_attempt": "1"}, "invalid_sha"),
        ({"sha": SHA + "\n", "run_id": "1", "run_attempt": "1"}, "invalid_sha"),
        ({"sha": SHA[:7], "run_id": "1", "run_attempt": "1"}, "invalid_sha"),
        ({"sha": 123, "run_id": "1", "run_attempt": "1"}, "invalid_sha"),
        ({"sha": SHA, "run_id": 1, "run_attempt": "1"}, "invalid_request"),
        ({"sha": SHA, "run_id": "0", "run_attempt": "1"}, "invalid_request"),
        ({"sha": SHA, "run_id": "1", "run_attempt": "1;id"}, "invalid_request"),
        ({"sha": SHA, "run_id": "1"}, "invalid_request"),
        ({"sha": SHA, "run_id": "1", "run_attempt": "1", "ref": "main"}, "invalid_request"),
        ([SHA], "invalid_request"),
    ],
)
def test_the_request_body_is_validated(body, status) -> None:
    with pytest.raises(gw.InvalidRequest) as error:
        gw.DeployRequest.parse(json.dumps(body).encode())
    assert error.value.status == status


def test_a_non_json_body_is_invalid() -> None:
    with pytest.raises(gw.InvalidRequest):
        gw.DeployRequest.parse(b"\xff not json")


# --- GitHub's keys: discovery, caching, rotation, failing closed ---------------------------


def test_keys_come_from_discovery_and_are_cached(verifier, issuer) -> None:
    for _ in range(3):
        assert not rejected(verifier, sign(claims()))
    assert issuer.fetches == [
        f"{ISSUER}/.well-known/openid-configuration",
        f"{ISSUER}/.well-known/jwks",
    ]


def test_a_rotated_key_is_picked_up_by_refreshing(verifier, issuer, keys_clock) -> None:
    assert not rejected(verifier, sign(claims()))
    # GitHub adds a new key and signs with it.
    issuer.jwks["keys"].append(jwk(KEY_B, "key-b"))
    keys_clock.now += gw.KEYS_MIN_REFRESH
    assert not rejected(verifier, sign(claims(), key=KEY_B, kid="key-b"))
    assert len(issuer.fetches) == 4


def test_unknown_key_ids_refresh_at_most_once_a_minute(verifier, issuer, keys_clock) -> None:
    assert not rejected(verifier, sign(claims()))
    for _ in range(5):
        assert rejected(verifier, sign(claims(), key=ATTACKER_KEY, kid=str(uuid.uuid4())))
    assert len(issuer.fetches) == 2
    keys_clock.now += gw.KEYS_MIN_REFRESH
    assert rejected(verifier, sign(claims(), key=ATTACKER_KEY, kid="again"))
    assert len(issuer.fetches) == 4


def test_a_removed_key_stops_working_after_the_cache_expires(verifier, issuer, keys_clock) -> None:
    assert not rejected(verifier, sign(claims()))
    issuer.jwks["keys"] = [jwk(KEY_B, "key-b")]
    keys_clock.now += gw.KEYS_TTL
    assert rejected(verifier, sign(claims()))
    assert not rejected(verifier, sign(claims(), key=KEY_B, kid="key-b"))


def test_failing_to_refresh_fails_closed(verifier, issuer, keys_clock) -> None:
    assert not rejected(verifier, sign(claims()))
    keys_clock.now += gw.KEYS_TTL
    issuer.fail = True
    with pytest.raises(gw.KeysUnavailable):
        verifier.verify(sign(claims()), REQUEST)
    # The old keys are not used afterwards either.
    with pytest.raises(gw.KeysUnavailable):
        verifier.verify(sign(claims()), REQUEST)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda i: i.discovery.update(issuer="https://evil.test"), id="other-issuer"),
        pytest.param(
            lambda i: i.discovery.update(id_token_signing_alg_values_supported=["HS256"]),
            id="only-hs256",
        ),
        pytest.param(
            lambda i: i.discovery.update(id_token_signing_alg_values_supported=["none"]),
            id="only-none",
        ),
        pytest.param(
            lambda i: i.discovery.pop("id_token_signing_alg_values_supported"), id="no-algs"
        ),
        pytest.param(
            lambda i: i.discovery.update(jwks_uri="http://issuer.test/jwks"), id="http-jwks"
        ),
        pytest.param(
            lambda i: i.discovery.update(jwks_uri="https://evil.test/jwks"), id="jwks-other-host"
        ),
        pytest.param(lambda i: i.jwks.update(keys=[]), id="no-keys"),
        pytest.param(
            lambda i: i.jwks.update(keys=[{"kty": "oct", "kid": "key-a", "k": "c2VjcmV0"}]),
            id="symmetric-key",
        ),
        pytest.param(
            lambda i: i.jwks.update(keys=[jwk(KEY_A, "key-a", alg="RS512")]), id="key-for-rs512"
        ),
        pytest.param(
            lambda i: i.jwks.update(keys=[jwk(KEY_A, "key-a", use="enc")]), id="encryption-key"
        ),
    ],
)
def test_unusable_discovery_or_keys_fail_closed(verifier, issuer, change) -> None:
    change(issuer)
    with pytest.raises(gw.KeysUnavailable):
        verifier.verify(sign(claims()), REQUEST)


def test_fetch_json_refuses_plain_http() -> None:
    with pytest.raises(gw.KeysUnavailable):
        gw.fetch_json("http://token.actions.githubusercontent.com/.well-known/openid-configuration")


# --- Replay protection ---------------------------------------------------------------------


@pytest.fixture
def store(tmp_path) -> "gw.Store":
    return gw.Store(tmp_path / "gateway.sqlite3")


def test_a_token_id_is_accepted_once(store, tmp_path) -> None:
    assert store.use_token("jti-1", int(time.time()) + 300, REQUEST)
    assert not store.use_token("jti-1", int(time.time()) + 300, REQUEST)
    assert store.use_token("jti-2", int(time.time()) + 300, REQUEST)
    # Persistent: a restarted gateway still refuses it.
    assert not gw.Store(tmp_path / "gateway.sqlite3").use_token("jti-1", 0, REQUEST)


def test_simultaneous_uses_of_one_token_id_let_exactly_one_through(store) -> None:
    barrier = threading.Barrier(16)
    results = []

    def use() -> None:
        barrier.wait()
        results.append(store.use_token("same-jti", int(time.time()) + 300, REQUEST))

    threads = [threading.Thread(target=use) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False] * 15 + [True]


def test_only_a_hash_of_the_token_id_is_stored(store, tmp_path) -> None:
    jti = "6f1e7c1a-2b3c-4d5e-8f90-0123456789ab"
    store.use_token(jti, int(time.time()) + 300, REQUEST)
    for path in tmp_path.glob("gateway.sqlite3*"):
        assert jti.encode() not in path.read_bytes()
    import sqlite3

    rows = (
        sqlite3.connect(tmp_path / "gateway.sqlite3")
        .execute("SELECT * FROM used_tokens")
        .fetchall()
    )
    assert rows[0][0] == hashlib.sha256(jti.encode()).hexdigest()
    assert rows[0][3:] == ("123456789", "1", SHA)


def test_used_token_ids_expire_after_the_grace_period(tmp_path) -> None:
    clock = Clock()
    store = gw.Store(tmp_path / "gateway.sqlite3", clock=clock)
    assert store.use_token("old", int(clock.now) + 300, REQUEST)
    clock.now += 300 + gw.REPLAY_GRACE - 1
    assert not store.use_token("old", int(clock.now) + 300, REQUEST)  # still remembered
    clock.now += 2
    store.use_token("other", int(clock.now) + 300, REQUEST)  # purges expired rows
    import sqlite3

    count = sqlite3.connect(tmp_path / "gateway.sqlite3").execute(
        "SELECT COUNT(*) FROM used_tokens WHERE jti_sha256 = ?",
        (hashlib.sha256(b"old").hexdigest(),),
    )
    assert count.fetchone() == (0,)


# --- One deploy at a time ------------------------------------------------------------------


RUN_B = gw.DeployRequest(OTHER_SHA, "222", "1")


def test_one_deploy_at_a_time(store) -> None:
    deployment, started = store.start_or_get(REQUEST)
    assert started and deployment.status == "running"
    again, started = store.start_or_get(REQUEST)
    assert not started and again.status == "running"
    with pytest.raises(gw.Busy):
        store.start_or_get(RUN_B)
    store.finish(REQUEST, "success", 0)
    deployment, started = store.start_or_get(RUN_B)
    assert started
    assert store.start_or_get(REQUEST)[0].status == "success"


def test_simultaneous_deploys_of_different_runs_start_only_one(store) -> None:
    barrier = threading.Barrier(8)
    outcomes = []

    def start(i: int) -> None:
        barrier.wait()
        try:
            outcomes.append(store.start_or_get(gw.DeployRequest(SHA, str(1000 + i), "1"))[1])
        except gw.Busy:
            outcomes.append("busy")

    threads = [threading.Thread(target=start, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert outcomes.count(True) == 1 and outcomes.count("busy") == 7


def test_a_deploy_left_running_by_a_stopped_gateway_is_marked_interrupted(store) -> None:
    store.start_or_get(REQUEST)
    store.mark_interrupted()
    assert store.start_or_get(REQUEST)[0].status == "interrupted"
    assert store.start_or_get(RUN_B)[1]  # no longer blocks new deploys


# --- Running the wrapper -------------------------------------------------------------------


def script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "fake-wrapper.sh"
    path.write_text("#!/bin/bash\nsha=$1\n" + body + "\n")
    return ["/bin/bash", str(path)]


def deployer(tmp_path, body: str, healthy: bool = True, timeout: float = 30) -> "gw.Deployer":
    return gw.Deployer(script(tmp_path, body), timeout, lambda: healthy, tmp_path / "logs")


DEPLOYING = 'echo "Deploying $sha (${sha:0:7})"'


def test_a_successful_deploy(tmp_path) -> None:
    body = f'echo "$@" > "{tmp_path}/args"\n{DEPLOYING}\necho "SpendWise is up"'
    assert deployer(tmp_path, body).run(REQUEST) == ("success", 0)
    # The wrapper gets exactly one argument: the SHA.
    assert (tmp_path / "args").read_text() == SHA + "\n"


def test_the_gateway_uses_the_one_sudo_wrapper() -> None:
    assert gw.DEPLOY_COMMAND == ("/usr/bin/sudo", "-n", "/usr/local/sbin/spendwise-deploy-sha")
    assert gw.DEPLOY_TIMEOUT < 3600


def test_a_failed_health_check_fails_the_deploy(tmp_path) -> None:
    assert deployer(tmp_path, DEPLOYING, healthy=False).run(REQUEST) == ("health_failed", 0)


def test_a_deploy_that_never_reports_the_commit_fails(tmp_path) -> None:
    body = f'echo "Deploying {OTHER_SHA} (1a87352)"'
    assert deployer(tmp_path, body).run(REQUEST) == ("deploy_failed", 0)


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (1, "deploy_failed"),
        (2, "deploy_failed"),
        (64, "invalid_sha"),
        (65, "superseded"),
        (75, "busy"),
        (124, "timeout"),
        (137, "timeout"),
    ],
)
def test_wrapper_failures_are_reported(tmp_path, code, status) -> None:
    assert deployer(tmp_path, f"{DEPLOYING}\nexit {code}").run(REQUEST) == (status, code)


def test_a_deploy_that_runs_too_long_is_stopped(tmp_path) -> None:
    started = time.monotonic()
    result = deployer(tmp_path, "sleep 60", timeout=0.5).run(REQUEST)
    assert result == ("timeout", None)
    assert time.monotonic() - started < 20


def test_deploy_output_is_bounded_and_redacted(tmp_path) -> None:
    token = sign(claims())
    body = "\n".join(
        [
            DEPLOYING,
            f'echo "leaked {token}"',
            'echo "POSTGRES_PASSWORD=hunter2hunter2"',
            'echo "DATABASE_URL=postgresql+psycopg://spendwise:hunter3hunter3@db:5432/spendwise"',
            'printf -- "-----BEGIN OPENSSH PRIVATE KEY-----\\nabc\\n"',
            'printf -- "-----END OPENSSH PRIVATE KEY-----\\n"',
            "head -c 3000000 /dev/zero | tr '\\0' x",
            'echo; echo "tail line"',
            f'echo "again {token}"',
        ]
    )
    assert deployer(tmp_path, body).run(REQUEST) == ("success", 0)
    (log,) = (tmp_path / "logs").glob("deploy-*.log")
    text = log.read_text()
    assert len(text) < 70_000
    assert "bytes omitted" in text and "tail line" in text
    for secret in (
        token,
        "hunter2hunter2",
        "hunter3hunter3",
        "BEGIN OPENSSH PRIVATE KEY-----\nabc",
    ):
        assert secret not in text
    assert "[redacted token]" in text
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_only_recent_deploy_logs_are_kept(tmp_path) -> None:
    d = deployer(tmp_path, DEPLOYING)
    for i in range(gw.KEEP_LOGS + 5):
        d.run(gw.DeployRequest(SHA, str(i + 1), "1"))
    assert len(list((tmp_path / "logs").glob("deploy-*.log"))) == gw.KEEP_LOGS


def test_health_check_gives_up(tmp_path) -> None:
    started = time.monotonic()
    assert not gw.check_health("https://127.0.0.1:9/api/health/ready", attempts=2, delay=0)
    assert time.monotonic() - started < 30


# --- The request handler -------------------------------------------------------------------


class FakeDeployer:
    def __init__(self, result=("success", 0)) -> None:
        self.result = result
        self.runs: list = []
        self.release = threading.Event()
        self.release.set()

    def run(self, request):
        self.runs.append(request)
        self.release.wait(10)
        return self.result


@pytest.fixture
def fake_deployer() -> FakeDeployer:
    return FakeDeployer()


@pytest.fixture
def gateway(verifier, store, fake_deployer) -> "gw.Gateway":
    return gw.Gateway(verifier, store, fake_deployer)


class Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, n: int) -> bytes:
        return self.data[:n]


def post(gateway, token: str | None, body: dict | bytes | None = None, path="/_deploy", **headers):
    data = body if isinstance(body, bytes) else json.dumps(body or request_body()).encode()
    sent = {"Content-Length": str(len(data)), "Content-Type": "application/json"}
    if token is not None:
        sent["Authorization"] = f"Bearer {token}"
    sent.update(headers)
    return gateway.handle_post(path, {k: v for k, v in sent.items() if v is not None}, Body(data))


def request_body(sha=SHA, run_id="123456789", run_attempt="1") -> dict:
    return {"sha": sha, "run_id": run_id, "run_attempt": run_attempt}


def finish(gateway) -> None:
    for thread in gateway.threads:
        thread.join(10)


def test_a_deploy_starts_and_reports_its_result(gateway, fake_deployer) -> None:
    code, answer = post(gateway, sign(claims()))
    assert (code, answer["status"]) == (202, "running")
    finish(gateway)
    assert fake_deployer.runs == [REQUEST]
    code, answer = post(gateway, sign(claims()))  # the same run polls with a fresh token
    assert (code, answer["status"], answer["exit_code"]) == (200, "success", 0)
    assert fake_deployer.runs == [REQUEST]  # polling never deploys again
    # Nothing about the token or its claims is returned.
    assert set(answer) == {
        "status",
        "sha",
        "run_id",
        "run_attempt",
        "started_at",
        "finished_at",
        "exit_code",
    }


@pytest.mark.parametrize("result", [("deploy_failed", 1), ("health_failed", 0), ("timeout", None)])
def test_failed_deploys_are_reported(gateway, fake_deployer, result) -> None:
    fake_deployer.result = result
    post(gateway, sign(claims()))
    finish(gateway)
    code, answer = post(gateway, sign(claims()))
    assert (code, answer["status"], answer["exit_code"]) == (200, *result)


def test_a_replayed_token_is_refused(gateway, fake_deployer) -> None:
    token = sign(claims())
    assert post(gateway, token)[0] == 202
    finish(gateway)
    assert post(gateway, token) == (409, {"status": "replay_rejected"})
    assert len(fake_deployer.runs) == 1


def test_simultaneous_requests_with_one_token_deploy_once(gateway, fake_deployer) -> None:
    token = sign(claims())
    barrier = threading.Barrier(8)
    codes = []

    def send() -> None:
        barrier.wait()
        codes.append(post(gateway, token)[0])

    threads = [threading.Thread(target=send) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    finish(gateway)
    assert sorted(codes) == [202] + [409] * 7
    assert len(fake_deployer.runs) == 1


def test_another_run_is_refused_while_a_deploy_runs(gateway, fake_deployer) -> None:
    fake_deployer.release.clear()
    assert post(gateway, sign(claims()))[0] == 202
    other = claims(sha=OTHER_SHA, run_id="222")
    assert post(gateway, sign(other), request_body(OTHER_SHA, "222")) == (409, {"status": "busy"})
    fake_deployer.release.set()
    finish(gateway)
    assert fake_deployer.runs == [REQUEST]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"path": "/_deploy/status"}, (404, "not_found")),
        ({"path": "/_deploy?x=1"}, (404, "not_found")),
        ({"path": "/api/health"}, (404, "not_found")),
        ({"Content-Length": None}, (411, "length_required")),
        ({"Content-Length": "-1"}, (411, "length_required")),
        ({"Content-Length": str(gw.MAX_BODY + 1)}, (413, "too_large")),
        ({"Transfer-Encoding": "chunked"}, (400, "invalid_request")),
        ({"Content-Type": "text/plain"}, (415, "unsupported_media_type")),
        ({"body": request_body(sha="main")}, (400, "invalid_sha")),
        ({"body": b"{"}, (400, "invalid_request")),
        ({"token": None}, (401, "unauthorized")),
        ({"Authorization": "Basic dXNlcjpwYXNz"}, (401, "unauthorized")),
        ({"Authorization": "Bearer"}, (401, "unauthorized")),
        ({"token": "not.a.token"}, (401, "unauthorized")),
    ],
)
def test_bad_requests_are_refused_without_deploying(
    gateway, fake_deployer, kwargs, expected
) -> None:
    kwargs = dict(kwargs)
    token = kwargs.pop("token", sign(claims()))
    body = kwargs.pop("body", None)
    path = kwargs.pop("path", "/_deploy")
    code, answer = post(gateway, token, body, path=path, **kwargs)
    assert (code, answer) == (expected[0], {"status": expected[1]})
    assert fake_deployer.runs == []


def test_unavailable_keys_are_a_503_not_an_acceptance(gateway, issuer, fake_deployer) -> None:
    issuer.fail = True
    assert post(gateway, sign(claims())) == (503, {"status": "unavailable"})
    assert fake_deployer.runs == []


def test_tokens_are_never_logged(gateway, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    good, bad = sign(claims()), sign(claims(event_name="pull_request"))
    post(gateway, good)
    finish(gateway)
    post(gateway, good)  # replay
    post(gateway, bad)
    text = caplog.text
    assert "Refused a deploy request: claim event_name does not match" in text
    assert "Refused a replayed token" in text
    for token in (good, bad):
        for part in token.split("."):
            assert part not in text


# --- HTTP over the Unix socket -------------------------------------------------------------


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path: str) -> None:
        super().__init__("localhost", timeout=10)
        self._path = path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(self._path)


@pytest.fixture
def server(gateway):
    # macOS limits Unix socket paths to 104 bytes; pytest's tmp_path can be longer.
    directory = Path(tempfile.mkdtemp(prefix="gw"))
    path = directory / "gateway.sock"
    srv = gw.GatewayServer(path, gateway)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield path
    srv.shutdown()
    srv.server_close()
    path.unlink(missing_ok=True)
    directory.rmdir()


def http_request(path: Path, method: str, target: str = "/_deploy", body=None, headers=None):
    conn = UnixHTTPConnection(str(path))
    conn.request(method, target, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, dict(response.getheaders()), data


def test_the_socket_is_not_world_accessible(server) -> None:
    assert oct(server.stat().st_mode & 0o777) == "0o660"


@pytest.mark.parametrize("method", ["GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_only_post_is_allowed(server, method) -> None:
    status, headers, _ = http_request(server, method)
    assert status == 405 and headers["Allow"] == "POST"


def test_only_the_deploy_route_exists(server) -> None:
    for target in ("/", "/api/health", "/_deploy/", "/_deploy/status", "/admin"):
        status, _, body = http_request(
            server, "POST", target, b"{}", {"Content-Type": "application/json"}
        )
        assert status == 404, target
        assert json.loads(body) == {"status": "not_found"}


def test_an_oversized_body_is_refused(server, fake_deployer) -> None:
    body = json.dumps(request_body() | {"pad": "x" * 5000}).encode()
    status, _, answer = http_request(
        server,
        "POST",
        body=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {sign(claims())}"},
    )
    assert (status, json.loads(answer)) == (413, {"status": "too_large"})
    assert fake_deployer.runs == []


def test_a_deploy_over_http(server, gateway, fake_deployer) -> None:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {sign(claims())}"}
    status, response_headers, answer = http_request(
        server, "POST", body=json.dumps(request_body()).encode(), headers=headers
    )
    assert status == 202 and json.loads(answer)["status"] == "running"
    assert response_headers["Cache-Control"] == "no-store"
    finish(gateway)
    assert fake_deployer.runs == [REQUEST]


# --- Settings ------------------------------------------------------------------------------


def installed_env() -> dict[str, str]:
    """deploy-gateway.env as installed: plus the health URL and systemd's STATE_DIRECTORY."""
    env = {}
    for line in (GATEWAY_DIR / "deploy-gateway.env").read_text().splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            env[name] = value
    return env | {
        "DEPLOY_GATEWAY_HEALTH_URL": "https://54.79.77.189.nip.io/api/health/ready",
        "STATE_DIRECTORY": "/var/lib/spendwise-deploy-gateway",
    }


def test_the_installed_settings_trust_exactly_this_repository() -> None:
    s = gw.Settings.from_env(installed_env())
    assert s.issuer == "https://token.actions.githubusercontent.com"
    assert s.audience == AUDIENCE
    assert s.subject == SUBJECT
    assert s.workflow_ref == WORKFLOW_REF
    assert s.socket_path == Path("/run/spendwise-deploy-gateway/gateway.sock")


def test_the_issuer_cannot_be_configured() -> None:
    s = gw.Settings.from_env(installed_env() | {"DEPLOY_GATEWAY_ISSUER": "https://evil.test"})
    assert s.issuer == gw.GITHUB_ISSUER


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DEPLOY_GATEWAY_AUDIENCE", ""),
        ("DEPLOY_GATEWAY_REPOSITORY", "SpendWise"),
        ("DEPLOY_GATEWAY_REPOSITORY_ID", "abc"),
        ("DEPLOY_GATEWAY_OWNER_ID", ""),
        ("DEPLOY_GATEWAY_REF", "main"),
        ("DEPLOY_GATEWAY_WORKFLOW", "ci.yml"),
        ("DEPLOY_GATEWAY_HEALTH_URL", "http://54.79.77.189.nip.io/api/health/ready"),
        ("DEPLOY_GATEWAY_SOCKET", "relative.sock"),
    ],
)
def test_invalid_settings_stop_the_gateway(name, value) -> None:
    with pytest.raises(ValueError, match=name):
        gw.Settings.from_env(installed_env() | {name: value})
