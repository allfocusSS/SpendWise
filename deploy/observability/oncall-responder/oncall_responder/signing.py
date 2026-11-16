"""Authentication and integrity for the alert receiver → on-call responder handoff.

HMAC-SHA256 over the request's method, path, timestamp, nonce and body, with a secret both sides
read from their environment (never from Git). The receiver signs; the responder verifies:

- tampering with the body, path or method changes the signature;
- the signature is compared in constant time (hmac.compare_digest);
- a timestamp more than MAX_SKEW seconds from the responder's clock is refused;
- a nonce is accepted once: a captured request replayed within the window is refused (409).
  Nonces are remembered only after the signature checked out, so unauthenticated traffic can't
  fill the memory, and they are kept exactly as long as their timestamp could still be accepted.

The receiver carries a copy of `sign()` (it is a single file in a minimal container); a unit test
checks that what it signs verifies here.
"""

import hashlib
import hmac
import re
import secrets
import threading
import time
from collections.abc import Mapping

VERSION = "v1"
SCHEME = "hmac-sha256-v1"
H_TIMESTAMP = "X-SpendWise-Timestamp"
H_NONCE = "X-SpendWise-Nonce"
H_SIGNATURE = "X-SpendWise-Signature"
MAX_SKEW = 300  # seconds
MAX_NONCES = 10_000
MIN_SECRET = 32  # characters

_TIMESTAMP = re.compile(r"[0-9]{10,12}")
_NONCE = re.compile(r"[0-9a-f]{32}")
_SIGNATURE = re.compile(rf"{VERSION}=([0-9a-f]{{64}})")


class Unauthorized(Exception):
    """The request isn't authentic; `code` says why (for the log, never for the caller)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Replayed(Exception):
    """An authentic request seen before."""


class Overloaded(Exception):
    """Too many distinct requests inside the window to remember them all."""


def signing_input(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return "\n".join(
        [VERSION, method.upper(), path, timestamp, nonce, hashlib.sha256(body).hexdigest()]
    ).encode()


def sign(
    secret: str,
    method: str,
    path: str,
    body: bytes,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """The three headers that authenticate this request."""
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    nonce = nonce or secrets.token_hex(16)
    digest = hmac.new(
        secret.encode(), signing_input(method, path, stamp, nonce, body), hashlib.sha256
    ).hexdigest()
    return {H_TIMESTAMP: stamp, H_NONCE: nonce, H_SIGNATURE: f"{VERSION}={digest}"}


class Nonces:
    """Nonces seen inside the window, each kept until its timestamp can no longer be accepted."""

    def __init__(self, limit: int = MAX_NONCES) -> None:
        self.limit = limit
        self.expires: dict[str, float] = {}
        # Requests are handled on several threads: looking a nonce up and storing it must be one
        # step, or two copies of one request, sent together, could both be "the first".
        self.lock = threading.Lock()

    def remember(self, nonce: str, timestamp: int, now: float) -> None:
        with self.lock:
            if len(self.expires) >= self.limit:
                self.expires = {n: e for n, e in self.expires.items() if e > now}
            if nonce in self.expires:
                raise Replayed
            if len(self.expires) >= self.limit:
                raise Overloaded
            self.expires[nonce] = timestamp + MAX_SKEW + 1


def verify(
    secret: str,
    method: str,
    path: str,
    headers: Mapping[str, str],
    body: bytes,
    nonces: Nonces,
    now: float | None = None,
) -> None:
    """Returns if the request is authentic and new; else raises (Unauthorized, Replayed, ...)."""
    now = time.time() if now is None else now
    stamp, nonce = headers.get(H_TIMESTAMP, ""), headers.get(H_NONCE, "")
    given = _SIGNATURE.fullmatch(headers.get(H_SIGNATURE, ""))
    if not (_TIMESTAMP.fullmatch(stamp) and _NONCE.fullmatch(nonce) and given):
        raise Unauthorized("missing-or-malformed-headers")
    expected = hmac.new(
        secret.encode(), signing_input(method, path, stamp, nonce, body), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected.encode(), given.group(1).encode()):
        raise Unauthorized("bad-signature")
    if abs(now - int(stamp)) > MAX_SKEW:
        raise Unauthorized("stale-timestamp")
    nonces.remember(nonce, int(stamp), now)
