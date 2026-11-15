"""The dashboard smoke test's stack: the real Compose stack plus Grafana's LGTM image.

Run from the repo root with `make dashboard` (or `cd backend && uv run pytest dashboard_smoke`).
Same isolation as the integration tests; see integration/lgtm.py.

Settings (all optional): SPENDWISE_DASHBOARD_PROJECT (default spendwise-dashboard),
SPENDWISE_DASHBOARD_PORT (18300, the app), SPENDWISE_DASHBOARD_GRAFANA_PORT (13000),
SPENDWISE_DASHBOARD_IMAGE (spendwise:dashboard), SPENDWISE_DASHBOARD_KEEP=1 to leave it running,
and SPENDWISE_DASHBOARD_LOG_FILE to write the run's container logs there (CI uploads it).
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
        "SPENDWISE_DASHBOARD",
        project="spendwise-dashboard",
        port=18300,
        grafana_port=13000,
        image="spendwise:dashboard",
    )


@pytest.fixture(scope="session")
def grafana(stack: Stack) -> Iterator[httpx.Client]:
    with lgtm.grafana_client(stack) as client:
        yield client
