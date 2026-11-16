"""The test stack's representation (backend/integration/stack.py).

pytest prints a failing test's fixtures, and that output goes to CI logs, so a Stack's repr must
not carry what it holds secret: the database password and the extra environment (which carries
the on-call signing secret).
"""

from integration.stack import Stack

SECRET = "an-on-call-signing-secret-" + "0123456789abcdef" * 2


def test_the_repr_leaves_out_the_database_password_and_the_extra_environment() -> None:
    stack = Stack(extra_env={"ONCALL_HMAC_SECRET": SECRET, "GRAFANA_PORT": "13200"})
    shown = repr(stack)
    assert SECRET not in shown and stack.db_password not in shown
    assert "ONCALL_HMAC_SECRET" not in shown and "GRAFANA_PORT" not in shown
    assert "project='spendwise-it'" in shown and "port=18000" in shown  # the rest is still there


def test_str_and_formatting_leave_them_out_too() -> None:
    stack = Stack(extra_env={"ONCALL_HMAC_SECRET": SECRET})
    for text in (str(stack), f"{stack}", f"{stack!r}", f"{[stack]}", f"{{'s': {stack!r}}}"):
        assert SECRET not in text and stack.db_password not in text


def test_the_secrets_still_reach_docker_compose() -> None:
    stack = Stack(extra_env={"ONCALL_HMAC_SECRET": SECRET})
    env = stack._env()
    assert env["POSTGRES_PASSWORD"] == stack.db_password and len(stack.db_password) == 32
    assert env["ONCALL_HMAC_SECRET"] == SECRET  # hidden from the repr, not from the stack


def test_two_stacks_still_compare_by_their_visible_and_hidden_fields_alike() -> None:
    first, second = Stack(), Stack()
    assert first != second  # each has its own random database password
    assert first == first
