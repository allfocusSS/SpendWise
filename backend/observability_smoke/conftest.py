"""The OpenTelemetry smoke test's stack: the real Compose stack plus the Collector.

Run from the repo root with `make observability` (or `cd backend && uv run pytest
observability_smoke`). Same isolation as the integration tests (integration/stack.py): its own
project, port and image tag, a scrubbed environment, and everything removed afterwards.

Settings (all optional): SPENDWISE_OTEL_PROJECT (default spendwise-otel), SPENDWISE_OTEL_PORT
(18200), SPENDWISE_OTEL_IMAGE (spendwise:otel), SPENDWISE_OTEL_KEEP=1 to leave it running, and
SPENDWISE_OTEL_LOG_FILE to write the run's container logs there (CI uploads it on failure).
"""

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from integration.stack import OBSERVABILITY_FILES, Stack, StackError

STOPS_COLLECTOR = "stops_collector"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", f"{STOPS_COLLECTOR}: stops the Collector for a while; always runs last"
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    items.sort(key=lambda item: item.get_closest_marker(STOPS_COLLECTOR) is not None)


@pytest.fixture(scope="session")
def stack(request: pytest.FixtureRequest) -> Iterator[Stack]:
    env = os.environ
    stack = Stack(
        project=env.get("SPENDWISE_OTEL_PROJECT", "spendwise-otel"),
        port=int(env.get("SPENDWISE_OTEL_PORT", "18200")),
        image=env.get("SPENDWISE_OTEL_IMAGE", "spendwise:otel"),
        keep=env.get("SPENDWISE_OTEL_KEEP") == "1",
        compose_files=OBSERVABILITY_FILES,
    )
    try:
        stack.check_prerequisites()
        stack.down(volumes=True)  # leftovers from an interrupted earlier run
        stack.up(build=True)
    except Exception as error:
        logs = stack.logs()
        if not stack.keep:
            with contextlib.suppress(StackError):
                stack.down(volumes=True)
        pytest.exit(f"The stack did not start:\n{error}\n--- logs ---\n{logs}", returncode=1)

    yield stack

    log_file = env.get("SPENDWISE_OTEL_LOG_FILE")
    if log_file:
        Path(log_file).write_text(stack.logs(tail=5000))
    if request.session.testsfailed:
        capture = request.config.pluginmanager.get_plugin("capturemanager")
        with capture.global_and_fixture_disabled():
            print(f"\n--- docker compose logs ({stack.project}) ---\n{stack.logs(tail=400)}")
    if not stack.keep:
        stack.down(volumes=True)
