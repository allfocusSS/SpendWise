"""The on-call smoke test's stack: the alerts stack plus the AI on-call responder.

Run from the repo root with `make oncall` (or `cd backend && uv run pytest oncall_smoke`).
Same isolation as the integration tests; see integration/lgtm.py.

The receiver and the responder share an HMAC secret. The run makes up its own (random, held in
memory and in the stack's environment, never written anywhere); SPENDWISE_ONCALL_HMAC_SECRET sets
one by hand when reproducing a run.

Settings (all optional): SPENDWISE_ONCALL_PROJECT (default spendwise-oncall),
SPENDWISE_ONCALL_PORT (18500, the app), SPENDWISE_ONCALL_GRAFANA_PORT (13200),
SPENDWISE_ONCALL_IMAGE (spendwise:oncall), SPENDWISE_ONCALL_KEEP=1 to leave it running, and
SPENDWISE_ONCALL_LOG_FILE to write the run's container logs there (CI uploads it).
"""

import os
import secrets
import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from integration import lgtm
from integration.stack import ONCALL_FILES, Stack

# The responder is standard library only and runs in its own container: the test imports its
# validators (the same ones the responder applies) straight from the repository.
RESPONDER = Path(__file__).resolve().parents[2] / "deploy" / "observability" / "oncall-responder"
sys.path.insert(0, str(RESPONDER))


@pytest.fixture(scope="session")
def stack(request: pytest.FixtureRequest) -> Iterator[Stack]:
    secret = os.environ.get("SPENDWISE_ONCALL_HMAC_SECRET") or secrets.token_hex(32)
    yield from lgtm.serve(
        request,
        "SPENDWISE_ONCALL",
        project="spendwise-oncall",
        port=18500,
        grafana_port=13200,
        image="spendwise:oncall",
        compose_files=ONCALL_FILES,
        extra_env={"ONCALL_HMAC_SECRET": secret},
    )


@pytest.fixture(scope="session")
def grafana(stack: Stack) -> Iterator[httpx.Client]:
    with lgtm.grafana_client(stack) as client:
        # Grafana's database and the provisioned Prometheus, Loki and Tempo data sources.
        lgtm.wait_until_ready(client)
        yield client
