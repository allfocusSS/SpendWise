"""AI parsing traffic for the dashboard and alert smoke tests, run inside the app container.

No HTTP endpoint calls AI parsing yet (Issue #2), so the smoke tests run the real provider
factory and the real metered provider in a one-off process inside the app container: the same
code, settings and OTLP export as the server, and nothing added to the application for it.

`send(stack, parses=5, outages=2, ...)` makes `parses` successful parses through the provider
the app's settings choose, then `outages` through the real metered wrapper around a provider
that is down (AIUnavailableError, error.type "provider"), and exports them all before it ends.

For a demo on the local dashboard stack (docs/observability.md, "Alerts"), print the program and
run it in the app container:

  uv run python -m integration.ai_traffic --parses 3 --outages 3 | docker compose \
    -f ../compose.yaml -f ../compose.override.yaml -f ../compose.dashboard.yaml exec -T app python -
"""

import argparse

from integration.stack import Stack

DONE = "ai traffic sent"


def program(*, text: str, category: str, parses: int, outages: int, outage_message: str) -> str:
    """The `python -c` program. It runs with the app's OTEL_* settings, against its code."""
    return f"""
import datetime
from app.ai import AIUnavailableError, build_ai_provider
from app.ai.metered import MeteredAIProvider
from app.ai.schemas import CategoryOption, TransactionDraftRequest
from app.core.config import get_settings
from app.observability import metrics as app_metrics, setup_telemetry, shutdown_telemetry

settings = get_settings()
telemetry = setup_telemetry(settings)
app_metrics.initialize(settings.ai_provider)
telemetry.meter_provider.force_flush()  # the zero series first, so every request is an increase

class Outage:
    name = settings.ai_provider
    def parse_transaction(self, request):
        raise AIUnavailableError({outage_message!r})
    def generate_insights(self, request):
        raise AIUnavailableError({outage_message!r})

request = TransactionDraftRequest(
    text={text!r},
    categories=[CategoryOption(id=1, name={category!r}, type="expense")],
    today=datetime.date(2026, 11, 15),
)
provider = build_ai_provider(settings)
if {parses}:
    provider.parse_transaction(request)
    # This process exports only when told to (it ends before the periodic export). A histogram
    # can't start at zero like the counters, so its first point goes out on its own: the rest
    # then arrive as an increase, which is what rate()/increase() queries need.
    telemetry.meter_provider.force_flush()
for _ in range({parses} - 1):
    provider.parse_transaction(request)
down = MeteredAIProvider(Outage())
for _ in range({outages}):
    try:
        down.parse_transaction(request)
    except AIUnavailableError:
        pass
shutdown_telemetry()
print({DONE!r})
"""


def send(stack: Stack, **kwargs) -> None:
    result = stack.compose("exec", "-T", "app", "python", "-c", program(**kwargs), timeout=120)
    assert DONE in result.stdout, result.stdout + result.stderr


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the AI traffic program (for python -).")
    parser.add_argument("--parses", type=int, default=5, help="successful parses")
    parser.add_argument("--outages", type=int, default=0, help="parses against a provider outage")
    args = parser.parse_args(argv)
    print(
        program(
            text="Taxi 2500 yesterday",
            category="Transport",
            parses=args.parses,
            outages=args.outages,
            outage_message="The AI provider is unavailable (demo)",
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
