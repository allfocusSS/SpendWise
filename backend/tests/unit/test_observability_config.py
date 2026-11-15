"""The OpenTelemetry Collector and the opt-in Compose overlay (docs/observability.md).

Read as data. The smoke test (observability_smoke/, CI job "Observability (OpenTelemetry)")
runs them for real.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
OVERLAY = ROOT / "compose.observability.yaml"
COLLECTOR_CONFIG = ROOT / "deploy" / "observability" / "otel-collector.yaml"
PINNED_IMAGE = re.compile(r"^otel/opentelemetry-collector:(\d+\.\d+\.\d+)@sha256:[0-9a-f]{64}$")


@pytest.fixture(scope="module")
def overlay() -> dict[str, Any]:
    return yaml.safe_load(OVERLAY.read_text())


@pytest.fixture(scope="module")
def collector() -> dict[str, Any]:
    return yaml.safe_load(COLLECTOR_CONFIG.read_text())


def test_the_collector_image_is_official_and_pinned(overlay) -> None:
    image = overlay["services"]["otel-collector"]["image"]
    match = PINNED_IMAGE.match(image)
    assert match, image  # an exact version and its digest, never :latest
    # The smoke test's parser is checked against output of this same version.
    assert (Path(__file__).parent / "data" / f"otelcol-{match.group(1)}-debug.txt").is_file()


def test_the_collector_is_reachable_from_the_app_only(overlay) -> None:
    collector = overlay["services"]["otel-collector"]
    assert "ports" not in collector and "expose" not in collector
    assert collector["networks"] == ["telemetry"]
    assert overlay["networks"]["telemetry"] == {"internal": True}
    app = overlay["services"]["app"]
    assert app["networks"] == ["default", "telemetry"]  # still reaches the database
    assert "ports" not in app  # the overlay publishes nothing new
    # Hardened and bounded; the config file is mounted read-only.
    assert collector["read_only"] is True
    assert collector["mem_limit"] == "256m"
    assert collector["volumes"] == [
        "./deploy/observability/otel-collector.yaml:/etc/otelcol/config.yaml:ro"
    ]


def test_the_overlay_turns_telemetry_on_for_the_app(overlay) -> None:
    app = overlay["services"]["app"]
    assert app["environment"]["OTEL_ENABLED"] == "true"
    assert app["environment"]["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://otel-collector:4318"
    assert app["environment"]["OTEL_TRACES_SAMPLE_RATIO"] == "1.0"
    # Started first, but never a dependency for serving requests.
    assert app["depends_on"] == {"otel-collector": {"condition": "service_started"}}


def test_the_collector_receives_otlp_http_only(collector) -> None:
    assert collector["receivers"] == {
        "otlp": {
            "protocols": {"http": {"endpoint": "0.0.0.0:4318", "max_request_body_size": 4194304}}
        }
    }


@pytest.mark.parametrize("signal", ["traces", "metrics", "logs"])
def test_every_signal_has_a_limited_batched_pipeline(collector, signal) -> None:
    pipeline = collector["service"]["pipelines"][signal]
    assert pipeline["receivers"] == ["otlp"]
    assert pipeline["processors"] == ["memory_limiter", "batch"]  # the limiter first
    assert pipeline["exporters"] == ["debug"]


def test_nothing_leaves_the_collector_yet(collector) -> None:
    # Only the debug exporter: no backend, endpoint or credential until the Grafana phase.
    assert set(collector["exporters"]) == {"debug"}
    assert collector["exporters"]["debug"] == {"verbosity": "detailed"}
    text = COLLECTOR_CONFIG.read_text()
    for forbidden in ("api_key", "password", "token", "authorization", "https://"):
        assert forbidden not in text.lower(), forbidden


def test_memory_limits_and_batching(collector) -> None:
    limiter = collector["processors"]["memory_limiter"]
    assert limiter["limit_mib"] + limiter["spike_limit_mib"] <= 256
    assert limiter["check_interval"] == "1s"
    batch = collector["processors"]["batch"]
    assert batch["send_batch_size"] <= batch["send_batch_max_size"]


@pytest.mark.parametrize(
    "path",
    [
        "compose.yaml",
        "compose.override.yaml",
        "deploy/aws/compose.aws.yaml",
        "deploy/aws/spendwise-stack.yaml",  # the instance's env files, written at first boot
        "render.yaml",
        "Dockerfile",
        "backend/scripts/start.sh",
    ],
)
def test_no_deployment_turns_telemetry_on_in_this_change(path) -> None:
    # Development (Render) and production (AWS) are ready for it but unchanged: telemetry is on
    # only where compose.observability.yaml is added.
    assert "OTEL_" not in (ROOT / path).read_text()
