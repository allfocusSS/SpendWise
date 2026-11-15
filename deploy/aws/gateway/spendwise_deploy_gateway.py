"""SpendWise deploy gateway: GitHub Actions OIDC in, one exact-SHA deploy out.

Installed by install-gateway.sh and run by systemd as the unprivileged user
spendwise-deploy-gateway (deploy/aws/README.md, "Mode B: GitHub OIDC deploy gateway"). It is not
part of the SpendWise application and shares nothing with its authentication.

Caddy forwards ``POST /_deploy`` to this service's Unix socket. Each request carries a GitHub
Actions OIDC token (``Authorization: Bearer``) and the JSON body
``{"sha": ..., "run_id": ..., "run_attempt": ...}``. The gateway:

1. verifies the token's RS256 signature with GitHub's published keys (OpenID discovery, then
   ``jwks_uri``), and its expiry, not-before, issued-at, issuer and audience;
2. requires the exact claims of a push to main of this repository, by the ci.yml workflow, on a
   GitHub-hosted runner, for the commit, run and attempt named in the body;
3. accepts each token once (its ``jti`` is recorded in SQLite);
4. starts ``sudo -n /usr/local/sbin/spendwise-deploy-sha <sha>`` in the background, at most one
   deploy at a time, and answers ``202 running``. Later requests from the same run, each with a
   fresh token, get the deploy's status until it is final.

Responses are small JSON objects with a ``status`` and never contain the token, its claims or the
deploy's output. The output is kept, bounded and redacted, in the state directory for operators.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.server
import json
import logging
import os
import re
import signal
import socketserver
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import jwt

log = logging.getLogger("spendwise-deploy-gateway")

GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
# The only signing algorithm accepted, and only while GitHub's discovery document advertises it.
# Never "none", never a symmetric (HS*) algorithm.
ALGORITHMS = ("RS256",)
DEPLOY_PATH = "/_deploy"
# The one privileged operation: root-owned, allowed by one sudo rule, for one SHA argument.
DEPLOY_COMMAND = ("/usr/bin/sudo", "-n", "/usr/local/sbin/spendwise-deploy-sha")
# The wrapper stops spendwise-deploy after 50 minutes; this is only a backstop.
DEPLOY_TIMEOUT = 3060.0

LEEWAY = 60  # seconds of clock skew allowed for exp, nbf and iat
MAX_TOKEN_AGE = 600  # a token must have been issued within the last ten minutes
REPLAY_GRACE = 86400  # used token IDs are kept this long after the token expires
MAX_BODY = 1024
# A declared request body up to this size is read, unused, before an early answer (see
# _Handler._discard_unread_body); a larger one is not.
MAX_DISCARD = 64 * 1024
MAX_TOKEN = 8192
MAX_DOCUMENT = 1024 * 1024  # discovery and JWKS documents
KEYS_TTL = 3600.0  # GitHub's keys are fetched again after an hour
KEYS_MIN_REFRESH = 60.0  # and at most once a minute for an unknown key ID
KEEP_DEPLOYMENTS = 200
KEEP_LOGS = 30

SHA = re.compile(r"[0-9a-f]{40}")
RUN_ID = re.compile(r"[1-9][0-9]{0,19}")
RUN_ATTEMPT = re.compile(r"[1-9][0-9]{0,4}")

RUNNING = "running"
SUCCESS = "success"
# The wrapper's exit codes (spendwise-deploy-sha); anything else non-zero is "deploy_failed".
EXIT_STATUSES = {64: "invalid_sha", 65: "superseded", 75: "busy", 124: "timeout", 137: "timeout"}


class TokenRejected(Exception):
    """The token is not acceptable. The reason is logged, never returned to the caller."""


class KeysUnavailable(Exception):
    """GitHub's discovery document or keys could not be fetched or are unusable (fail closed)."""


class InvalidRequest(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class Busy(Exception):
    """Another deploy is running."""


@dataclass(frozen=True)
class Settings:
    audience: str
    repository: str  # owner/name
    repository_id: str
    owner_id: str
    ref: str  # refs/heads/main
    workflow: str  # .github/workflows/ci.yml
    socket_path: Path
    state_dir: Path
    health_url: str
    issuer: str = GITHUB_ISSUER

    @property
    def subject(self) -> str:
        # GitHub's immutable subject format: owner and repository with their numeric IDs.
        owner, name = self.repository.split("/")
        return f"repo:{owner}@{self.owner_id}/{name}@{self.repository_id}:ref:{self.ref}"

    @property
    def workflow_ref(self) -> str:
        return f"{self.repository}/{self.workflow}@{self.ref}"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        """Read /etc/spendwise/deploy-gateway.env (via systemd). The issuer is not configurable."""

        def get(name: str, pattern: str) -> str:
            value = env.get(name, "")
            if not re.fullmatch(pattern, value):
                raise ValueError(f"{name} is missing or invalid")
            return value

        return cls(
            audience=get("DEPLOY_GATEWAY_AUDIENCE", r"[A-Za-z0-9._:-]{1,128}"),
            repository=get("DEPLOY_GATEWAY_REPOSITORY", r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+"),
            repository_id=get("DEPLOY_GATEWAY_REPOSITORY_ID", r"[1-9][0-9]*"),
            owner_id=get("DEPLOY_GATEWAY_OWNER_ID", r"[1-9][0-9]*"),
            ref=get("DEPLOY_GATEWAY_REF", r"refs/heads/[A-Za-z0-9._/-]+"),
            workflow=get("DEPLOY_GATEWAY_WORKFLOW", r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml"),
            socket_path=Path(get("DEPLOY_GATEWAY_SOCKET", r"/[A-Za-z0-9_./-]+\.sock")),
            # systemd's StateDirectory= sets STATE_DIRECTORY.
            state_dir=Path(get("STATE_DIRECTORY", r"/[A-Za-z0-9_./-]+")),
            health_url=get("DEPLOY_GATEWAY_HEALTH_URL", r"https://[A-Za-z0-9.-]+(:[0-9]+)?/\S*"),
        )


@dataclass(frozen=True)
class DeployRequest:
    sha: str
    run_id: str
    run_attempt: str

    @classmethod
    def parse(cls, body: bytes) -> DeployRequest:
        try:
            data = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise InvalidRequest("invalid_request") from e
        if not isinstance(data, dict) or set(data) != {"sha", "run_id", "run_attempt"}:
            raise InvalidRequest("invalid_request")
        sha, run_id, run_attempt = data["sha"], data["run_id"], data["run_attempt"]
        if not isinstance(sha, str) or not SHA.fullmatch(sha):
            raise InvalidRequest("invalid_sha")
        if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
            raise InvalidRequest("invalid_request")
        if not isinstance(run_attempt, str) or not RUN_ATTEMPT.fullmatch(run_attempt):
            raise InvalidRequest("invalid_request")
        return cls(sha, run_id, run_attempt)


# --- GitHub's signing keys -----------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # a redirect becomes an error instead of being followed


_opener = urllib.request.build_opener(_NoRedirect)


def fetch_json(url: str) -> Any:
    """GET an HTTPS JSON document (certificate verified, no redirects, at most 1 MiB)."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise KeysUnavailable(f"not an HTTPS URL: {url}")
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with _opener.open(request, timeout=10) as response:
            body = response.read(MAX_DOCUMENT + 1)
    except (urllib.error.URLError, OSError) as e:
        raise KeysUnavailable(f"could not fetch {url}: {e}") from e
    if len(body) > MAX_DOCUMENT:
        raise KeysUnavailable(f"{url} is too large")
    try:
        return json.loads(body)
    except ValueError as e:
        raise KeysUnavailable(f"{url} is not JSON") from e


class GitHubKeys:
    """GitHub's token signing keys, from OpenID discovery and its jwks_uri.

    Cached for KEYS_TTL. An unknown key ID fetches them again (at most once per
    KEYS_MIN_REFRESH), so GitHub's key rotation keeps working. Any failure fails closed.
    """

    def __init__(
        self,
        issuer: str,
        fetch: Callable[[str], Any] = fetch_json,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer = issuer
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._keys: dict[str, Any] = {}
        self._algorithms: tuple[str, ...] = ()
        self._fetched_at: float | None = None

    def signing_key(self, kid: str) -> tuple[Any, tuple[str, ...]]:
        """The public key for ``kid`` and the algorithms GitHub currently advertises."""
        with self._lock:
            now = self._clock()
            age = None if self._fetched_at is None else now - self._fetched_at
            unknown = kid not in self._keys
            if age is None or age >= KEYS_TTL or (unknown and age >= KEYS_MIN_REFRESH):
                self._refresh(now)
            if kid not in self._keys:
                raise TokenRejected("unknown signing key ID")
            return self._keys[kid], self._algorithms

    def refresh(self) -> int:
        with self._lock:
            self._refresh(self._clock())
            return len(self._keys)

    def _refresh(self, now: float) -> None:
        # Whatever happens, the old keys are not used past this point.
        self._keys, self._algorithms, self._fetched_at = {}, (), None
        discovery = self._fetch(f"{self._issuer}/.well-known/openid-configuration")
        if not isinstance(discovery, dict) or discovery.get("issuer") != self._issuer:
            raise KeysUnavailable("discovery document is for another issuer")
        advertised = discovery.get("id_token_signing_alg_values_supported")
        if not isinstance(advertised, list):
            raise KeysUnavailable("discovery document lists no signing algorithms")
        algorithms = tuple(a for a in ALGORITHMS if a in advertised)
        if not algorithms:
            raise KeysUnavailable(f"no acceptable signing algorithm in {advertised!r}")
        jwks_uri = discovery.get("jwks_uri")
        issuer_host = urllib.parse.urlsplit(self._issuer).hostname
        if (
            not isinstance(jwks_uri, str)
            or urllib.parse.urlsplit(jwks_uri).scheme != "https"
            or urllib.parse.urlsplit(jwks_uri).hostname != issuer_host
        ):
            raise KeysUnavailable("jwks_uri is not an HTTPS URL of the issuer")
        jwks = self._fetch(jwks_uri)
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            raise KeysUnavailable("JWKS has no keys")
        keys = {}
        for jwk in jwks["keys"]:
            if not isinstance(jwk, dict) or jwk.get("kty") != "RSA":
                continue
            kid, alg = jwk.get("kid"), jwk.get("alg", "RS256")
            if not isinstance(kid, str) or not kid or jwk.get("use", "sig") != "sig":
                continue
            if alg not in algorithms:
                continue
            try:
                keys[kid] = jwt.PyJWK(jwk, algorithm=alg).key
            except (jwt.PyJWKError, ValueError, TypeError):
                continue
        if not keys:
            raise KeysUnavailable("JWKS has no usable RSA signing keys")
        self._keys, self._algorithms, self._fetched_at = keys, algorithms, now


# --- Token verification --------------------------------------------------------------------


class TokenVerifier:
    def __init__(
        self,
        settings: Settings,
        keys: GitHubKeys,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._keys = keys
        self._clock = clock

    def verify(self, token: str, request: DeployRequest) -> dict[str, Any]:
        """The token's claims, if it authorises deploying ``request``; else TokenRejected."""
        s = self._settings
        if not token or len(token) > MAX_TOKEN:
            raise TokenRejected("token missing or too long")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as e:
            raise TokenRejected("malformed token") from e
        alg = header.get("alg")
        if alg not in ALGORITHMS:  # rejects "none" and every symmetric algorithm
            raise TokenRejected(f"algorithm {alg!r} is not accepted")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > 200:
            raise TokenRejected("token has no key ID")
        key, advertised = self._keys.signing_key(kid)
        if alg not in advertised:
            raise TokenRejected(f"algorithm {alg!r} is not advertised by the issuer")
        try:
            claims = jwt.decode(
                token,
                key=key,
                algorithms=[alg],
                audience=s.audience,
                issuer=s.issuer,
                leeway=LEEWAY,
                options={
                    "require": ["exp", "nbf", "iat", "iss", "aud", "sub", "jti"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_nbf": True,
                    "verify_iat": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "strict_aud": True,
                },
            )
        except jwt.InvalidTokenError as e:
            raise TokenRejected(f"invalid token ({type(e).__name__})") from e

        now = self._clock()
        if claims["iss"] != s.issuer or claims["aud"] != s.audience:  # exact, not "contains"
            raise TokenRejected("issuer or audience is not an exact match")
        for name in ("exp", "nbf", "iat"):
            if not isinstance(claims[name], int) or isinstance(claims[name], bool):
                raise TokenRejected(f"claim {name} is not a number")
        if claims["iat"] > now + LEEWAY or claims["iat"] < now - MAX_TOKEN_AGE - LEEWAY:
            raise TokenRejected("token was not issued just now")
        jti = claims["jti"]
        if not isinstance(jti, str) or not jti or len(jti) > 256:
            raise TokenRejected("claim jti is missing or invalid")

        expected = {
            "sub": s.subject,
            "repository": s.repository,
            "repository_id": s.repository_id,
            "repository_owner_id": s.owner_id,
            "ref": s.ref,
            "ref_type": "branch",
            "event_name": "push",
            "runner_environment": "github-hosted",
            "workflow_ref": s.workflow_ref,
            "sha": request.sha,
            "run_id": request.run_id,
            "run_attempt": request.run_attempt,
        }
        for name, value in expected.items():
            if claims.get(name) != value:
                raise TokenRejected(f"claim {name} does not match")
        return claims


# --- State: used token IDs and deployments -------------------------------------------------


@dataclass(frozen=True)
class Deployment:
    sha: str
    run_id: str
    run_attempt: str
    status: str
    started_at: int
    finished_at: int | None
    exit_code: int | None

    def public(self) -> dict[str, Any]:
        """What the caller may see: no output, no token, no claims."""
        return {
            "status": self.status,
            "sha": self.sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
        }


class Store:
    """SQLite in the gateway's state directory. Every operation is one atomic transaction.

    used_tokens: one row per accepted token (a SHA-256 of its jti, never the token), until a day
    after the token expired. Its primary key makes a second use fail, also under concurrency.
    deployments: one row per run attempt. A partial unique index allows one "running" row.
    """

    def __init__(self, path: Path, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self._clock = clock
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS used_tokens (
                    jti_sha256 TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL,
                    used_at INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    run_attempt TEXT NOT NULL,
                    sha TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deployments (
                    run_id TEXT NOT NULL,
                    run_attempt TEXT NOT NULL,
                    sha TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at INTEGER NOT NULL,
                    finished_at INTEGER,
                    exit_code INTEGER,
                    PRIMARY KEY (run_id, run_attempt)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_running_deployment
                    ON deployments (status) WHERE status = 'running';
                """
            )

    @contextlib.contextmanager
    def _connect(self):
        db = sqlite3.connect(self._path, timeout=30, isolation_level=None)
        try:
            yield db
        finally:
            db.close()

    def use_token(self, jti: str, expires_at: int, request: DeployRequest) -> bool:
        """Record the token as used. False if it was used before."""
        now = int(self._clock())
        digest = hashlib.sha256(jti.encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM used_tokens WHERE expires_at < ?", (now - REPLAY_GRACE,))
            try:
                db.execute(
                    "INSERT INTO used_tokens VALUES (?, ?, ?, ?, ?, ?)",
                    (digest, expires_at, now, request.run_id, request.run_attempt, request.sha),
                )
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                return False
            db.execute("COMMIT")
            return True

    def start_or_get(self, request: DeployRequest) -> tuple[Deployment, bool]:
        """This run's deployment, started now (True) if it had none; Busy if another runs."""
        now = int(self._clock())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                row = db.execute(
                    "SELECT sha, run_id, run_attempt, status, started_at, finished_at, exit_code"
                    " FROM deployments WHERE run_id = ? AND run_attempt = ?",
                    (request.run_id, request.run_attempt),
                ).fetchone()
                if row:
                    db.execute("COMMIT")
                    deployment = Deployment(*row)
                    if deployment.sha != request.sha:
                        raise InvalidRequest("invalid_request")
                    return deployment, False
                if db.execute("SELECT 1 FROM deployments WHERE status = 'running'").fetchone():
                    raise Busy
                db.execute(
                    "INSERT INTO deployments (run_id, run_attempt, sha, status, started_at)"
                    " VALUES (?, ?, ?, 'running', ?)",
                    (request.run_id, request.run_attempt, request.sha, now),
                )
                db.execute(
                    "DELETE FROM deployments WHERE rowid NOT IN"
                    " (SELECT rowid FROM deployments ORDER BY started_at DESC LIMIT ?)",
                    (KEEP_DEPLOYMENTS,),
                )
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        return Deployment(
            request.sha, request.run_id, request.run_attempt, RUNNING, now, None, None
        ), True

    def finish(self, request: DeployRequest, status: str, exit_code: int | None) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE deployments SET status = ?, finished_at = ?, exit_code = ?"
                " WHERE run_id = ? AND run_attempt = ? AND status = 'running'",
                (status, int(self._clock()), exit_code, request.run_id, request.run_attempt),
            )

    def mark_interrupted(self) -> None:
        """At startup: a deploy still "running" was stopped with the previous gateway process."""
        with self._connect() as db:
            db.execute(
                "UPDATE deployments SET status = 'interrupted', finished_at = ?"
                " WHERE status = 'running'",
                (int(self._clock()),),
            )


# --- Running the deploy --------------------------------------------------------------------

_REDACTIONS = [
    (re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*"), "[redacted token]"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S
        ),
        "[redacted private key]",
    ),
    (
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY)[A-Z0-9_]*)\s*[=:]\s*\S+"
        ),
        r"\1=[redacted]",
    ),
    (re.compile(r"(://[^/\s:@]+:)[^@\s/]+@"), r"\1[redacted]@"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


class BoundedOutput:
    """The first and last part of a command's output; the middle is dropped and counted."""

    def __init__(self, head: int = 16384, tail: int = 49152) -> None:
        self._head_limit, self._tail_limit = head, tail
        self.head, self.tail, self.omitted = bytearray(), bytearray(), 0

    def add(self, chunk: bytes) -> None:
        room = self._head_limit - len(self.head)
        if room > 0:
            self.head += chunk[:room]
            chunk = chunk[room:]
        self.tail += chunk
        excess = len(self.tail) - self._tail_limit
        if excess > 0:
            del self.tail[:excess]
            self.omitted += excess

    def consume(self, stream: BinaryIO) -> None:
        while chunk := stream.read1(65536):
            self.add(chunk)

    def contains_line_starting(self, prefix: bytes) -> bool:
        return any(
            line.startswith(prefix) for part in (self.head, self.tail) for line in part.split(b"\n")
        )

    def text(self) -> str:
        middle = f"\n[... {self.omitted} bytes omitted ...]\n" if self.omitted else ""
        return redact(
            self.head.decode("utf-8", "replace") + middle + self.tail.decode("utf-8", "replace")
        )


def check_health(url: str, attempts: int = 6, delay: float = 5.0) -> bool:
    """GET url until it answers 200 (TLS verified), a bounded number of times."""
    for attempt in range(attempts):
        try:
            with _opener.open(urllib.request.Request(url), timeout=10) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        if attempt + 1 < attempts:
            time.sleep(delay)
    return False


class Deployer:
    def __init__(
        self,
        command: Sequence[str],
        timeout: float,
        health_check: Callable[[], bool],
        log_dir: Path,
    ) -> None:
        self._command = tuple(command)
        self._timeout = timeout
        self._health_check = health_check
        self._log_dir = log_dir

    def run(self, request: DeployRequest) -> tuple[str, int | None]:
        """Deploy request.sha; the final status and the wrapper's exit code."""
        output = BoundedOutput()
        proc = subprocess.Popen(
            [*self._command, request.sha],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
            close_fds=True,
        )
        reader = threading.Thread(target=output.consume, args=(proc.stdout,), daemon=True)
        reader.start()
        try:
            code: int | None = proc.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired:
            code = None
            # sudo relays the signal to the root command, if it lets us signal it at all; the
            # wrapper's own time limit is what reliably stops it.
            with contextlib.suppress(OSError):
                proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
        reader.join(timeout=5)
        self._write_log(request, output)

        if code is None:
            return "timeout", None
        if code != 0:
            return EXIT_STATUSES.get(code, "deploy_failed"), code
        # spendwise-deploy prints "Deploying <ref> (<short SHA>)" after checking the commit out.
        if not output.contains_line_starting(f"Deploying {request.sha} ".encode()):
            return "deploy_failed", code
        if not self._health_check():
            return "health_failed", code
        return SUCCESS, code

    def _write_log(self, request: DeployRequest, output: BoundedOutput) -> None:
        try:
            self._log_dir.mkdir(mode=0o700, exist_ok=True)
            path = self._log_dir / f"deploy-{request.run_id}-{request.run_attempt}.log"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"sha {request.sha}, run {request.run_id} attempt {request.run_attempt}\n")
                f.write(output.text())
            logs = sorted(self._log_dir.glob("deploy-*.log"), key=lambda p: p.stat().st_mtime)
            for old in logs[:-KEEP_LOGS]:
                old.unlink(missing_ok=True)
        except OSError:
            log.exception("Could not write the deploy log")


# --- HTTP ----------------------------------------------------------------------------------


def bearer_token(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or " " in token:
        return None
    return token


class Gateway:
    def __init__(self, verifier: TokenVerifier, store: Store, deployer: Deployer) -> None:
        self._verifier = verifier
        self._store = store
        self._deployer = deployer
        self.threads: list[threading.Thread] = []

    def handle_post(
        self, path: str, headers: Mapping[str, str], body: BinaryIO
    ) -> tuple[int, dict[str, Any]]:
        if path != DEPLOY_PATH:
            return 404, {"status": "not_found"}
        if headers.get("Transfer-Encoding"):
            return 400, {"status": "invalid_request"}
        length = headers.get("Content-Length") or ""
        if not length.isdigit():
            return 411, {"status": "length_required"}
        if int(length) > MAX_BODY:
            return 413, {"status": "too_large"}
        content_type = (headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "application/json":
            return 415, {"status": "unsupported_media_type"}
        data = body.read(int(length))
        if len(data) != int(length):
            return 400, {"status": "invalid_request"}
        try:
            request = DeployRequest.parse(data)
        except InvalidRequest as e:
            return 400, {"status": e.status}

        token = bearer_token(headers.get("Authorization"))
        if token is None:
            log.warning("Refused a deploy request: no bearer token")
            return 401, {"status": "unauthorized"}
        try:
            claims = self._verifier.verify(token, request)
        except TokenRejected as e:
            log.warning("Refused a deploy request: %s", e)
            return 401, {"status": "unauthorized"}
        except KeysUnavailable as e:
            log.error("Refused a deploy request, GitHub's keys are unavailable: %s", e)
            return 503, {"status": "unavailable"}

        if not self._store.use_token(claims["jti"], claims["exp"], request):
            log.warning("Refused a replayed token for run %s", request.run_id)
            return 409, {"status": "replay_rejected"}
        try:
            deployment, started = self._store.start_or_get(request)
        except Busy:
            log.warning("Refused run %s: another deploy is running", request.run_id)
            return 409, {"status": "busy"}
        except InvalidRequest as e:
            return 400, {"status": e.status}
        if started:
            log.info(
                "Deploying %s for run %s attempt %s",
                request.sha,
                request.run_id,
                request.run_attempt,
            )
            thread = threading.Thread(target=self._deploy, args=(request,), daemon=True)
            self.threads.append(thread)
            thread.start()
        return (202 if deployment.status == RUNNING else 200), deployment.public()

    def _deploy(self, request: DeployRequest) -> None:
        try:
            status, exit_code = self._deployer.run(request)
        except Exception:
            log.exception("The deploy of %s could not run", request.sha)
            status, exit_code = "deploy_failed", None
        self._store.finish(request, status, exit_code)
        log.info(
            "Deploy of %s for run %s: %s (exit %s)", request.sha, request.run_id, status, exit_code
        )


class _CountingReader:
    """The request body stream, counting what the gateway read from it."""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self.consumed = 0

    def read(self, size: int = -1) -> bytes:
        data = self._stream.read(size)
        self.consumed += len(data)
        return data


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "spendwise-deploy-gateway"
    sys_version = ""
    timeout = 15  # seconds per connection read/write

    def address_string(self) -> str:
        return "unix"  # the only client is Caddy, on the socket

    def log_message(self, format: str, *args: Any) -> None:
        # Request lines and status codes only; headers (and so the token) are never logged.
        log.info("%s", (format % args)[:300])

    def do_POST(self) -> None:
        body = _CountingReader(self.rfile)
        try:
            code, payload = self.server.gateway.handle_post(self.path, self.headers, body)
        except Exception:
            log.exception("Deploy request failed")
            code, payload = 500, {"status": "error"}
        self._discard_unread_body(body.consumed)
        self._send(code, payload)

    def _method_not_allowed(self) -> None:
        self._discard_unread_body(0)
        self._send(405, {"status": "method_not_allowed"}, {"Allow": "POST"})

    do_GET = do_HEAD = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = _method_not_allowed

    def _discard_unread_body(self, consumed: int) -> None:
        """Read the rest of the declared body, if any, before an early answer.

        Answers such as 404, 405, 411, 413 and 415 come before (or without) reading the body, and
        the connection closes after every answer. Closing while the client is still sending the
        body it declared breaks that write (EPIPE on a Unix socket), so the client, Caddy, never
        sees the answer and reports an error instead. Bounded: a declared body over MAX_DISCARD
        is not read (that client gets the answer and a closed connection), and the connection's
        timeout stops a client that never sends what it declared.
        """
        length = self.headers.get("Content-Length") or ""
        if self.headers.get("Transfer-Encoding") or not length.isdigit():
            return
        remaining = int(length) - consumed
        if not 0 < remaining <= MAX_DISCARD:
            return
        try:
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 65536))
                if not chunk:
                    break
                remaining -= len(chunk)
        except TimeoutError:
            pass  # the client stalled; answer anyway, then close

    def _send(
        self, code: int, payload: dict[str, Any], headers: Mapping[str, str] | None = None
    ) -> None:
        body = json.dumps(payload).encode() + b"\n"
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


class GatewayServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """HTTP on a Unix socket only: the gateway has no network port at all."""

    daemon_threads = True

    def __init__(self, socket_path: Path, gateway: Gateway) -> None:
        self.gateway = gateway
        with contextlib.suppress(FileNotFoundError):
            if not stat.S_ISSOCK(socket_path.lstat().st_mode):
                raise RuntimeError(f"{socket_path} exists and is not a socket")
            socket_path.unlink()  # left over from a previous run
        super().__init__(str(socket_path), _Handler)
        os.chmod(socket_path, 0o660)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="check the settings and fetch GitHub's signing keys, then exit",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)
    settings = Settings.from_env(os.environ)
    keys = GitHubKeys(settings.issuer)
    if args.check:
        count = keys.refresh()
        print(f"subject       {settings.subject}")
        print(f"workflow_ref  {settings.workflow_ref}")
        print(f"audience      {settings.audience}")
        print(f"signing keys  {count} from {settings.issuer}")
        return 0

    store = Store(settings.state_dir / "gateway.sqlite3")
    store.mark_interrupted()
    deployer = Deployer(
        DEPLOY_COMMAND,
        DEPLOY_TIMEOUT,
        lambda: check_health(settings.health_url),
        settings.state_dir / "logs",
    )
    gateway = Gateway(TokenVerifier(settings, keys), store, deployer)
    server = GatewayServer(settings.socket_path, gateway)

    def stop(signum: int, frame: Any) -> None:
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    log.info("Listening on %s for %s", settings.socket_path, settings.subject)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        with contextlib.suppress(FileNotFoundError):
            settings.socket_path.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
