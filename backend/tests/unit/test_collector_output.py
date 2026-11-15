"""The smoke test's reader of the Collector's debug output (observability_smoke/).

data/otelcol-0.165.0-debug.txt is real `docker compose logs otel-collector` output of the pinned
Collector, abridged to one log record, one span and one metric. If a Collector upgrade changes
the format, this fails before the smoke test does.
"""

from pathlib import Path

from observability_smoke.collector_output import received

SAMPLE = (Path(__file__).parent / "data" / "otelcol-0.165.0-debug.txt").read_text()
RESOURCE = {
    "service.name": "spendwise-api",
    "deployment.environment.name": "local",
    "service.version": "e63ad28dfe1514ed6eabc2141e347dfc5b2de239",
}


def test_each_signal_becomes_a_block_with_its_resource() -> None:
    output = received(SAMPLE)
    assert [block.signal for block in output.blocks] == ["logs", "traces", "metrics"]
    for block in output.blocks:
        assert RESOURCE.items() <= block.resource.items()
        assert block.resource["telemetry.sdk.language"] == "python"


def test_spans_are_read_with_their_ids_and_attributes() -> None:
    (span,) = received(SAMPLE).spans
    assert span.name == "POST /api/auth/signup"
    assert span.trace_id == "f7010304b0c62aa55d4166ed5edb29c7"
    assert span.span_id == "f826baba72a008a8"
    assert span.parent_id == ""
    assert span.attributes["http.route"] == "/api/auth/signup"
    assert span.attributes["http.response.status_code"] == "201"


def test_log_records_are_read_with_their_body_and_trace() -> None:
    (record,) = received(SAMPLE).logs
    assert record.severity == "INFO"
    assert record.body == "Telemetry on: OTLP/HTTP to http://otel-collector:4318, 100% of traces"
    assert (record.trace_id, record.span_id) == ("", "")


def test_metrics_are_read_with_their_data_point_attributes() -> None:
    output = received(SAMPLE)
    (metric,) = output.metrics
    assert (metric.name, metric.unit) == ("http.server.request.duration", "s")
    assert output.points_of("http.server.request.duration") == [
        {
            "url.scheme": "http",
            "network.protocol.version": "1.1",
            "http.request.method": "POST",
            "http.route": "/api/auth/signup",
            "http.response.status_code": "201",
        }
    ]


def test_the_collectors_own_log_lines_are_not_telemetry() -> None:
    assert (
        received("otel-collector-1  | 2026-11-15T10:46:54.725Z\tinfo\tStarting otelcol...").blocks
        == []
    )
    assert received("").blocks == []
