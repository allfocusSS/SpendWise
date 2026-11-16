"""Text hygiene (oncall_responder/privacy.py): folding look-alikes, mixed scripts, scrubbing."""

import pytest
from oncall_responder.privacy import fold, mixed_script, plain, scrub
from oncall_support import PATTERN_CANARIES, SECRET


@pytest.mark.parametrize(
    ("text", "folded"),
    [
        ("\uff43\uff55\uff52\uff4c", "curl"),  # fullwidth
        ("\U0001d41c\U0001d42e\U0001d42b\U0001d425", "curl"),  # mathematical bold
        ("\u24d2\u24e4\u24e1\u24db", "curl"),  # circled
        ("c\u0301u\u0300rl", "curl"),  # combining accents
        ("caf\u00e9", "cafe"),  # an accent is dropped for matching only
        ("c\u200bu\u2060rl\ufeff", "curl"),  # invisible characters
        ("\u0441url", "curl"),  # Cyrillic с
        ("\u0455\u0441\u0440", "scp"),  # all Cyrillic
        ("\u03b1ws", "aws"),  # Greek α
        ("c\u057drl", "curl"),  # Armenian ս
        ("\u1d04url", "curl"),  # Latin small capital c
        ("rm \u2011rf", "rm -rf"),  # non-breaking hyphen
        ("rm \u2212rf", "rm -rf"),  # minus sign
        ("plain ASCII stays", "plain ASCII stays"),
    ],
)
def test_fold_reads_text_as_the_ascii_it_imitates(text, folded) -> None:
    assert fold(text) == folded


def test_fold_is_for_matching_only_and_never_changes_what_is_stored() -> None:
    text = "caf\u00e9 \u041f\u0440\u043e\u0432\u0435\u0440\u044c"
    assert plain(text, 100) == text  # the text itself is untouched by folding


@pytest.mark.parametrize(
    ("text", "mixed"),
    [
        ("\u0441url", True),  # Cyrillic + Latin, with a look-alike
        ("\u03b1ws", True),
        ("c\u057drl", True),
        ("Spend\u0434\u043e\u043c", True),  # a look-alike (о) inside a mixed word: conservative
        ("curl", False),
        ("\u043f\u0430\u043d\u0435\u043b\u044c", False),  # all Cyrillic
        ("\u03c0\u03af\u03bd\u03b1\u03ba\u03b1\u03c2", False),  # all Greek
        ("120 \u03bcs", False),  # micro: Greek μ beside Latin s, and μ imitates nothing in ASCII
        ("120 \u00b5s", False),
        ("resistance \u03a9", False),
        ("\u3072\u3089\u304c\u306a\u30ab\u30bf\u30ab\u30ca", False),  # hiragana + katakana
        ("check the \u043f\u0430\u043d\u0435\u043b\u044c panel", False),  # separate words
        ("", False),
        ("123 456", False),
    ],
)
def test_a_word_that_mixes_alphabets_with_a_look_alike_is_flagged(text, mixed) -> None:
    assert mixed_script(text) is mixed


def test_fullwidth_letters_are_not_a_mix_of_alphabets() -> None:
    # NFKC makes them Latin first; the policy then reads them as the ASCII they are.
    assert mixed_script("\uff43\uff55\uff52\uff4c") is False


@pytest.mark.parametrize("name", sorted(PATTERN_CANARIES))
def test_scrub_removes_every_shape_of_secret_and_personal_data(name) -> None:
    value = PATTERN_CANARIES[name]
    cleaned = scrub(f"before {value} after")
    assert value not in cleaned and scrub(cleaned) == cleaned  # and it is idempotent


def test_scrub_removes_the_responders_own_secret_wherever_it_appears() -> None:
    assert SECRET not in scrub(f"a {SECRET} b {SECRET}", (SECRET,))


def test_scrub_can_leave_a_commit_sha_alone_only_when_asked() -> None:
    sha = "5ca7067" + "0" * 33
    assert scrub(f"version {sha}", keep_sha=True) == f"version {sha}"
    assert sha not in scrub(f"version {sha}")  # free text never gets the exemption
