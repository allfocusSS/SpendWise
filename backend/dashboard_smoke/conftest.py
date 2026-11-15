"""The dashboard smoke test's stack: the real Compose stack plus Grafana's LGTM image.

Run from the repo root with `make dashboard` (or `cd backend && uv run pytest dashboard_smoke`).
Same isolation as the integration tests (integration/stack.py): its own project, ports and image
tag, a scrubbed environment, and everything removed afterwards.

Settings (all optional): SPENDWISE_DASHBOARD_PROJECT (default spendwise-dashboard),
SPENDWISE_DASHBOARD_PORT (18300, the app), SPENDWISE_DASHBOARD_GRAFANA_PORT (13000),
SPENDWISE_DASHBOARD_IMAGE (spendwise:dashboard), SPENDWISE_DASHBOARD_KEEP=1 to leave it running,
and SPENDWISE_DASHBOARD_LOG_FILE to write the run's container logs there (CI uploads it).
"""

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from integration.stack import DASHBOARD_FILES, Stack, StackError


@pytest.fixture(scope="session")
def stack(request: pytest.FixtureRequest) -> Iterator[Stack]:
    env = os.environ
    stack = Stack(
        project=env.get("SPENDWISE_DASHBOARD_PROJECT", "spendwise-dashboard"),
        port=int(env.get("SPENDWISE_DASHBOARD_PORT", "18300")),
        image=env.get("SPENDWISE_DASHBOARD_IMAGE", "spendwise:dashboard"),
        keep=env.get("SPENDWISE_DASHBOARD_KEEP") == "1",
        compose_files=DASHBOARD_FILES,
        extra_env={"GRAFANA_PORT": env.get("SPENDWISE_DASHBOARD_GRAFANA_PORT", "13000")},
    )
    try:
        stack.check_prerequisites()
        stack.down(volumes=True)  # leftovers from an interrupted earlier run
        stack.up(build=True)  # waits for the app and for LGTM's own health check
    except Exception as error:
        logs = stack.logs()
        if not stack.keep:
            with contextlib.suppress(StackError):
                stack.down(volumes=True)
        pytest.exit(f"The stack did not start:\n{error}\n--- logs ---\n{logs}", returncode=1)

    yield stack

    log_file = env.get("SPENDWISE_DASHBOARD_LOG_FILE")
    if log_file:
        Path(log_file).write_text(stack.logs(tail=3000))
    if request.session.testsfailed:
        capture = request.config.pluginmanager.get_plugin("capturemanager")
        with capture.global_and_fixture_disabled():
            print(f"\n--- docker compose logs ({stack.project}) ---\n{stack.logs(tail=300)}")
    if not stack.keep:
        stack.down(volumes=True)


@pytest.fixture(scope="session")
def grafana(stack: Stack) -> Iterator[httpx.Client]:
    """Grafana's HTTP API (anonymous, read-only), the only port the stack publishes."""
    port = stack.extra_env["GRAFANA_PORT"]
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
        yield client
