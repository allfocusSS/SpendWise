"""Reads what the Collector's debug exporter printed (verbosity: detailed) back into data.

`docker compose logs otel-collector` holds one block per export: "ResourceSpans #N",
"ResourceMetrics #N" or "ResourceLog #N", followed by the resource's attributes and then its
spans, metrics or log records. The format belongs to the pinned Collector version
(compose.observability.yaml); tests/unit/test_collector_output.py checks the parser against a
sample of it.
"""

import re
from dataclasses import dataclass, field

# "otel-collector-1  | " in front of every line of `docker compose logs`.
_COMPOSE_PREFIX = re.compile(r"^[\w.-]+\s+\| ?")
# A new log entry of the Collector itself: "2026-11-15T10:47:04.742Z\tinfo\t…".
_ENTRY = re.compile(r"^\d{4}-\d\d-\d\dT\S+\t\w+\t(.*)$")
_BLOCK = re.compile(r"^(ResourceSpans|ResourceMetrics|ResourceLog) #\d+$")
_ATTRIBUTE = re.compile(r"^\s+-> ([^:]+): (\w+)\((.*)\)$")
_DESCRIPTOR = re.compile(r"^\s+-> (\w+): (.*)$")
_SPAN_FIELD = re.compile(r"^\s+(Trace ID|Parent ID|ID|Name)\s+: ?(.*)$")
_LOG_FIELD = re.compile(r"^(SeverityText|Body|Trace ID|Span ID): ?(.*)$")
SIGNALS = {"ResourceSpans": "traces", "ResourceMetrics": "metrics", "ResourceLog": "logs"}
_SPAN_FIELDS = {"Trace ID": "trace_id", "Parent ID": "parent_id", "ID": "span_id", "Name": "name"}
_LOG_FIELDS = {"SeverityText": "severity", "Trace ID": "trace_id", "Span ID": "span_id"}


@dataclass
class Span:
    name: str = ""
    trace_id: str = ""
    span_id: str = ""
    parent_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class LogRecord:
    severity: str = ""
    body: str = ""
    trace_id: str = ""
    span_id: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass
class Metric:
    name: str = ""
    unit: str = ""
    points: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Block:
    """One resource of one export, and what it carried."""

    signal: str  # traces, metrics or logs
    resource: dict[str, str] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    logs: list[LogRecord] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)


def _value(kind: str, raw: str) -> str:
    return raw.strip() if kind != "Str" else raw


def parse(text: str) -> list[Block]:
    blocks: list[Block] = []
    block: Block | None = None
    # Where "-> key: Type(value)" lines currently go.
    target: dict[str, str] | None = None
    in_descriptor = False

    for raw in text.splitlines():
        line = _COMPOSE_PREFIX.sub("", raw, count=1)
        entry = _ENTRY.match(line)
        if entry:  # a new Collector log entry: maybe the start of a block, else the end of one
            started = _BLOCK.match(entry.group(1))
            block = Block(SIGNALS[started.group(1)]) if started else None
            if block:
                blocks.append(block)
            target, in_descriptor = None, False
            continue
        if block is None:
            continue
        if line.startswith("\t{"):  # the exporter's closing context: the block is complete
            block = None
            continue

        if line == "Resource attributes:":
            target = block.resource
        elif line.startswith("Span #"):
            block.spans.append(Span())
            target = None
        elif line.startswith("LogRecord #"):
            block.logs.append(LogRecord())
            target = None
        elif line.startswith("Metric #"):
            block.metrics.append(Metric())
            target = None
        elif line == "Descriptor:":
            in_descriptor, target = True, None
        elif re.match(r"^\w+DataPoints #\d+$", line):
            in_descriptor = False
            block.metrics[-1].points.append({})
            target = None
        elif line == "Data point attributes:":
            target = block.metrics[-1].points[-1]
        elif line == "Attributes:":
            if block.spans and block.signal == "traces":
                target = block.spans[-1].attributes
            elif block.logs:
                target = block.logs[-1].attributes
        elif in_descriptor and (descriptor := _DESCRIPTOR.match(line)):
            key, value = descriptor.groups()
            if key == "Name":
                block.metrics[-1].name = value
            elif key == "Unit":
                block.metrics[-1].unit = value
        elif target is not None and (attribute := _ATTRIBUTE.match(line)):
            key, kind, value = attribute.groups()
            target[key] = _value(kind, value)
        elif block.signal == "traces" and block.spans and (span_field := _SPAN_FIELD.match(line)):
            key, value = span_field.groups()
            setattr(block.spans[-1], _SPAN_FIELDS[key], value.strip())
        elif block.signal == "logs" and block.logs and (log_field := _LOG_FIELD.match(line)):
            key, value = log_field.groups()
            if key == "Body":  # Str(text)
                body = re.fullmatch(r"\w+\((.*)\)", value)
                block.logs[-1].body = body.group(1) if body else value
            else:
                setattr(block.logs[-1], _LOG_FIELDS[key], value.strip())
        else:  # any other line ends a run of attributes
            target = None
    return blocks


@dataclass
class Received:
    """Everything the Collector printed, by signal."""

    blocks: list[Block]

    def of(self, signal: str) -> list[Block]:
        return [b for b in self.blocks if b.signal == signal]

    @property
    def spans(self) -> list[Span]:
        return [s for b in self.of("traces") for s in b.spans]

    @property
    def logs(self) -> list[LogRecord]:
        return [r for b in self.of("logs") for r in b.logs]

    @property
    def metrics(self) -> list[Metric]:
        return [m for b in self.of("metrics") for m in b.metrics]

    def spans_named(self, name: str) -> list[Span]:
        return [s for s in self.spans if s.name == name]

    def logs_saying(self, body: str) -> list[LogRecord]:
        return [r for r in self.logs if r.body == body]

    def points_of(self, metric: str) -> list[dict[str, str]]:
        return [p for m in self.metrics if m.name == metric for p in m.points]


def received(text: str) -> Received:
    return Received(parse(text))
