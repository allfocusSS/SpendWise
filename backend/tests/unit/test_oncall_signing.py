"""The receiver → responder handoff's authentication (oncall_responder/signing.py).

HMAC over method, path, timestamp, nonce and body; a clock window; a nonce accepted once. The
receiver carries its own copy of `sign()`, and one test here keeps the two in step.
"""

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from oncall_responder import signing
from oncall_responder.signing import (
    H_NONCE,
    H_SIGNATURE,
    H_TIMESTAMP,
    MAX_SKEW,
    Nonces,
    Overloaded,
    Replayed,
    Unauthorized,
    sign,
    verify,
)
from oncall_support import NOW, SECRET

BODY = json.dumps({"schema": "spendwise.incident.v1"}).encode()
RECEIVER = Path(__file__).resolve().parents[3] / "deploy/observability/alert-receiver"


def signed(**overrides) -> dict:
    return sign(SECRET, "POST", "/incidents", BODY, timestamp=int(NOW), nonce="ab" * 16) | overrides


def check(headers: dict, body: bytes = BODY, nonces: Nonces | None = None, now: float = NOW, **kw):
    verify(
        kw.get("secret", SECRET),
        kw.get("method", "POST"),
        kw.get("path", "/incidents"),
        headers,
        body,
        nonces or Nonces(),
        now,
    )


def test_a_signed_request_is_accepted() -> None:
    nonces = Nonces()
    check(signed(), nonces=nonces)
    assert len(nonces.expires) == 1


def test_the_headers_carry_no_secret() -> None:
    headers = signed()
    assert set(headers) == {H_TIMESTAMP, H_NONCE, H_SIGNATURE}
    assert SECRET not in "".join(headers.values())
    assert headers[H_SIGNATURE].startswith("v1=") and len(headers[H_SIGNATURE]) == 3 + 64


@pytest.mark.parametrize(
    "change",
    [
        {"body": BODY + b" "},
        {"body": b'{"schema": "spendwise.incident.v2"}'},
        {"path": "/incidents/"},
        {"path": "/alerts"},
        {"method": "PUT"},
        {"secret": SECRET + "x"},
        {"secret": "another-secret-" + "0" * 32},
    ],
    ids=["body-padded", "body-replaced", "path-slash", "path-other", "method", "key+", "key-other"],
)
def test_changing_anything_signed_breaks_the_signature(change) -> None:
    body = change.pop("body", BODY)
    with pytest.raises(Unauthorized) as refused:
        check(signed(), body=body, **change)
    assert refused.value.code == "bad-signature"


@pytest.mark.parametrize(
    ("header", "value"),
    [
        (H_TIMESTAMP, str(int(NOW) + 1)),
        (H_NONCE, "cd" * 16),
        (H_SIGNATURE, "v1=" + "0" * 64),
    ],
)
def test_changing_a_header_breaks_the_signature(header, value) -> None:
    with pytest.raises(Unauthorized) as refused:
        check(signed(**{header: value}))
    assert refused.value.code == "bad-signature"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {H_TIMESTAMP: str(int(NOW))},
        {H_TIMESTAMP: "yesterday", H_NONCE: "ab" * 16, H_SIGNATURE: "v1=" + "a" * 64},
        {H_TIMESTAMP: str(int(NOW)), H_NONCE: "AB" * 16, H_SIGNATURE: "v1=" + "a" * 64},
        {H_TIMESTAMP: str(int(NOW)), H_NONCE: "ab" * 15, H_SIGNATURE: "v1=" + "a" * 64},
        {H_TIMESTAMP: str(int(NOW)), H_NONCE: "ab" * 16, H_SIGNATURE: "v2=" + "a" * 64},
        {H_TIMESTAMP: str(int(NOW)), H_NONCE: "ab" * 16, H_SIGNATURE: "v1=" + "A" * 64},
        {H_TIMESTAMP: str(int(NOW)), H_NONCE: "ab" * 16, H_SIGNATURE: "v1=" + "a" * 63},
        {H_TIMESTAMP: str(int(NOW)), H_NONCE: "ab" * 16, H_SIGNATURE: ""},
    ],
)
def test_missing_or_malformed_headers_are_refused(headers) -> None:
    with pytest.raises(Unauthorized) as refused:
        check(headers)
    assert refused.value.code == "missing-or-malformed-headers"


@pytest.mark.parametrize(
    ("skew", "accepted"),
    [(-MAX_SKEW, True), (MAX_SKEW, True), (-MAX_SKEW - 1, False), (MAX_SKEW + 1, False)],
)
def test_only_timestamps_inside_the_window_are_accepted(skew, accepted) -> None:
    headers = sign(SECRET, "POST", "/incidents", BODY, timestamp=int(NOW) + skew)
    if accepted:
        check(headers)
        return
    with pytest.raises(Unauthorized) as refused:
        check(headers)
    assert refused.value.code == "stale-timestamp"


def test_a_request_is_accepted_once() -> None:
    nonces = Nonces()
    headers = signed()
    check(headers, nonces=nonces)
    with pytest.raises(Replayed):
        check(headers, nonces=nonces)
    # A different nonce is a different request, even with the same body.
    check(sign(SECRET, "POST", "/incidents", BODY, timestamp=int(NOW)), nonces=nonces)


def test_a_forgery_does_not_use_up_the_genuine_nonce() -> None:
    nonces = Nonces()
    forged = signed(**{H_SIGNATURE: "v1=" + "0" * 64})
    with pytest.raises(Unauthorized):
        check(forged, nonces=nonces)
    assert nonces.expires == {}  # nonces are remembered only after the signature checks out
    check(signed(), nonces=nonces)


def test_a_replay_after_the_window_is_stale_not_a_second_acceptance() -> None:
    nonces = Nonces()
    check(signed(), nonces=nonces)
    later = NOW + MAX_SKEW + 10
    with pytest.raises(Unauthorized) as refused:
        check(signed(), nonces=nonces, now=later)
    assert refused.value.code == "stale-timestamp"


def test_the_nonce_memory_is_bounded_and_never_forgets_a_usable_nonce() -> None:
    nonces = Nonces(limit=2)
    for index in range(2):
        nonces.remember(f"{index:032x}", int(NOW), NOW)
    with pytest.raises(Overloaded):  # full of nonces that could still be replayed
        nonces.remember("f" * 32, int(NOW), NOW)
    with pytest.raises(Replayed):
        nonces.remember(f"{0:032x}", int(NOW), NOW)
    nonces.remember("f" * 32, int(NOW) + 2 * MAX_SKEW, NOW + 2 * MAX_SKEW)  # the old ones expired
    assert len(nonces.expires) == 1


def test_signatures_are_compared_in_constant_time() -> None:
    tree = ast.parse(Path(signing.__file__).read_text())
    calls = {ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "hmac.compare_digest" in calls
    comparisons = [n for n in ast.walk(tree) if isinstance(n, ast.Compare)]
    assert not [c for c in comparisons if "expected" in ast.unparse(c) or "given" in ast.unparse(c)]


def test_what_the_receiver_signs_the_responder_verifies() -> None:
    spec = importlib.util.spec_from_file_location("alert_receiver", RECEIVER / "alert_receiver.py")
    receiver = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = receiver
    spec.loader.exec_module(receiver)
    headers = receiver.sign(SECRET, "POST", receiver.HANDOFF_PATH, BODY)
    assert set(headers) == {H_TIMESTAMP, H_NONCE, H_SIGNATURE}
    assert receiver.HANDOFF_PATH == "/incidents"
    nonces = Nonces()
    verify(SECRET, "POST", "/incidents", headers, BODY, nonces)  # a real clock: signed just now
    with pytest.raises(Replayed):
        verify(SECRET, "POST", "/incidents", headers, BODY, nonces)
    with pytest.raises(Unauthorized):
        verify(
            SECRET,
            "POST",
            "/incidents",
            receiver.sign("other-" + SECRET, "POST", "/incidents", BODY),
            BODY,
            Nonces(),
        )
