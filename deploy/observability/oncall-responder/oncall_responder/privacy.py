"""Text hygiene for everything the responder reads, prompts with, stores or logs.

Telemetry and incident text is untrusted data. Two things happen to it before it goes any
further: `plain()` makes it single-line plain text of bounded length (no markup, no control or
format characters), and `scrub()` replaces what looks like a secret or personal data with a
marker. Patterns can only catch what has a recognizable shape (an email, a token, an
`Authorization` header). Free text, such as a transaction description, has none, so it is kept
out structurally instead: the stored report never holds a raw log line, and metric labels pass a
fixed allowlist (evidence.py).
"""

import re
import unicodedata
from collections.abc import Iterator

TAG = re.compile(r"<[^>]*>")
SHA = re.compile(r"\b[0-9a-f]{40}\b")

_REDACTIONS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"(?i)\b(?:proxy-)?authorization\b\s*[:=]\s*[^\r\n]{1,300}"),
        "Authorization: [redacted]",
    ),
    (re.compile(r"(?i)\b(?:set-)?cookie\b\s*[:=]\s*[^\r\n]{1,500}"), "Cookie: [redacted]"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}"), r"\1 [redacted]"),
    (
        re.compile(
            r"(?i)\b([\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|credential|session|cookie)"
            r"[\w.-]*)\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"
        ),
        r"\1=[redacted]",
    ),
    (re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]*@"), r"\1[redacted]@"),
    (re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{8,}"), "[redacted-key]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[redacted-key]"),
    (
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
        "[redacted-key]",
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*"), "[redacted-token]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"), "[redacted-email]"),
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), "[redacted-token]"),
    # Money in minor units and other long numbers: nothing in a log line needs nine digits.
    (re.compile(r"\b\d{9,}\b"), "[redacted-number]"),
]


def plain(value: object, limit: int) -> str | None:
    """Single-line plain text of at most `limit` characters, or None if it is empty or not text."""
    if not isinstance(value, str):
        return None
    value = TAG.sub(" ", value[: limit * 4])
    value = "".join(" " if unicodedata.category(c).startswith("C") else c for c in value)
    value = " ".join(value.split())
    if len(value) > limit:
        value = value[: limit - 1].rstrip() + "…"
    return value or None


# Letters, in other scripts, that read as an ASCII letter: "code point:the letter it imitates".
# NFKC already turns fullwidth, mathematical and circled letters into ASCII; these are the rest.
_LOOKALIKES = (
    # Cyrillic, lower case
    "0430:a 0433:r 0435:e 0455:s 0456:i 0458:j 043A:k 04CF:l 043C:m 043D:h 043E:o 0440:p 0441:c "
    "0442:t 0443:y 0445:x 0501:d 051B:q 051D:w 04BB:h 04AF:y "
    # Cyrillic, upper case
    "0410:A 0412:B 0415:E 041A:K 041C:M 041D:H 041E:O 0420:P 0421:C 0422:T 0425:X 0423:Y 0405:S "
    "0406:I 0408:J "
    # Greek
    "03B1:a 03B5:e 03B9:i 03BA:k 03BD:v 03BF:o 03C1:p 03C4:t 03C5:u 03C7:x 03C9:w 03B3:y "
    "0391:A 0392:B 0395:E 0396:Z 0397:H 0399:I 039A:K 039C:M 039D:N 039F:O 03A1:P 03A4:T 03A5:Y "
    "03A7:X "
    # Latin: dotless i, script g, small capitals
    "0131:i 0251:a 0261:g 0280:r 1D04:c 1D1C:u 029F:l 026A:i 0274:n 1D05:d 1D07:e 1D0F:o 1D18:p "
    "1D1B:t A731:s 1D21:w 028F:y 1D0B:k 1D0D:m 029C:h 1D00:a 0299:b 0262:g "
    # Armenian
    "057D:u 0585:o 0578:n 0581:g 0570:h "
    # Dashes and the minus sign: "rm \u2011rf"
    "2010:- 2011:- 2012:- 2013:- 2014:- 2015:- 2212:-"
)
_FOLD = {
    ord(chr(int(code, 16))): letter
    for code, letter in (pair.split(":") for pair in _LOOKALIKES.split())
}


def fold(text: str) -> str:
    """`text` as the plain ASCII it would read as, for matching a denylist against.

    Only for matching: the text itself is kept (or rejected) as written. Compatibility forms
    (fullwidth, circled, mathematical) become ASCII, accents, combining marks and invisible
    format characters are dropped, and look-alike letters from other scripts become the letter
    they imitate.
    """
    text = unicodedata.normalize("NFKC", text)
    stripped = "".join(
        c
        for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) not in {"Mn", "Me", "Cf"}
    )
    return stripped.translate(_FOLD)


def mixed_script(text: str) -> bool:
    """Does any one word mix scripts using a letter that imitates an ASCII one ("сurl")?

    Words of one script, in any language, are fine. So is a mix of letters that look like nothing
    in ASCII, such as the Greek μ in "μs" (microseconds) or Japanese kana: only a look-alike
    letter can make one word read as another.
    """
    for word in re.findall(r"[^\W\d_]+", unicodedata.normalize("NFKC", text)):
        scripts = {unicodedata.name(c, "?").split()[0] for c in word}
        if len(scripts) > 1 and any(ord(c) in _FOLD for c in word):
            return True
    return False


def scrub(text: str, secrets: tuple[str, ...] = (), keep_sha: bool = False) -> str:
    """`text` with secrets and personal data replaced by markers (idempotent).

    `secrets` are exact values to remove wherever they appear (the responder's own HMAC secret).
    `keep_sha` leaves 40-character hex strings alone: for evidence built from allowlisted labels,
    where `service_version` is a commit SHA. Free text (logs, alert text, a model's words) never
    gets it, so a token that looks like a SHA is still redacted there.
    """
    for secret in secrets:
        if len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    held: list[str] = []

    def hold(found: re.Match) -> str:
        held.append(found.group(0))
        return f"\x00{len(held) - 1}\x00"

    if keep_sha:
        text = SHA.sub(hold, text)
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    for index, sha in enumerate(held):
        text = text.replace(f"\x00{index}\x00", sha)
    return text


def safe_text(value: object, limit: int, secrets: tuple[str, ...] = ()) -> str | None:
    """`plain()` then `scrub()`: what free text may become before it is prompted or stored."""
    text = plain(value, limit)
    return scrub(text, secrets) if text else None


def strings(data: object, path: str = "") -> Iterator[tuple[str, str]]:
    """Every string in a JSON-like structure with the path to it (dict keys included)."""
    if isinstance(data, str):
        yield path, data
    elif isinstance(data, dict):
        for key, value in data.items():
            yield f"{path}.{key}" if path else str(key), str(key)
            yield from strings(value, f"{path}.{key}" if path else str(key))
    elif isinstance(data, list | tuple):
        for index, value in enumerate(data):
            yield from strings(value, f"{path}[{index}]")
