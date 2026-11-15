"""The alert smoke test's stack: the real Compose stack, Grafana's LGTM image and the receiver.

Run from the repo root with `make alerts` (or `cd backend && uv run pytest alerts_smoke`).
Same isolation as the integration tests; see integration/lgtm.py.

Settings (all optional): SPENDWISE_ALERTS_PROJECT (default spendwise-alerts),
SPENDWISE_ALERTS_PORT (18400, the app), SPENDWISE_ALERTS_GRAFANA_PORT (13100),
SPENDWISE_ALERTS_IMAGE (spendwise:alerts), SPENDWISE_ALERTS_KEEP=1 to leave it running, and
SPENDWISE_ALERTS_LOG_FILE to write the run's container logs there (CI uploads it).
"""

from collections.abc import Iterator

import httpx
import pytest

from integration import lgtm
from integration.stack import Stack


@pytest.fixture(scope="session")
def stack(request: pytest.FixtureRequest) -> Iterator[Stack]:
    yield from lgtm.serve(
        request,
        "SPENDWISE_ALERTS",
        project="spendwise-alerts",
        port=18400,
        grafana_port=13100,
        image="spendwise:alerts",
    )


@pytest.fixture(scope="session")
def grafana(stack: Stack) -> Iterator[httpx.Client]:
    with lgtm.grafana_client(stack) as client:
        yield client
