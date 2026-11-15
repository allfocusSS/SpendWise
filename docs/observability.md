# Observability (OpenTelemetry)

The SpendWise API can send **traces, metrics and logs** over OTLP/HTTP to an OpenTelemetry
Collector. Locally and in CI, the Collector's only exporter is `debug`, which prints everything
it receives, and an automated check proves all three signals arrive. Telemetry is **off by
default** and is **not yet enabled in development (Render) or production (AWS)**. Grafana,
dashboards, alerts and the AI on-call responder are later steps; none of them exists yet.

```mermaid
flowchart LR
    subgraph app["SpendWise API (FastAPI)"]
        req["HTTP requests<br/>FastAPI instrumentation"] --> tp["TracerProvider<br/>sampler + redaction"]
        req --> mp["MeterProvider<br/>bounded HTTP metrics"]
        logs["logging.getLogger('app.…')"] --> lp["LoggerProvider<br/>(OTel logging handler)"]
    end
    tp -- "OTLP/HTTP /v1/traces" --> recv
    mp -- "OTLP/HTTP /v1/metrics" --> recv
    lp -- "OTLP/HTTP /v1/logs" --> recv
    subgraph col["OpenTelemetry Collector 0.165.0 (internal network only)"]
        recv["otlp receiver<br/>(HTTP :4318)"] --> ml["memory_limiter"] --> batch["batch"] --> debug["debug exporter<br/>(Collector log)"]
    end
    batch -. "later: otlp_http / prometheus_remote_write" .-> backends["Tempo · Mimir · Loki<br/>(Grafana, not in this change)"]
```

| Piece | Where |
|---|---|
| SDK setup, FastAPI instrumentation, process lifecycle | `backend/app/observability/telemetry.py` |
| What telemetry never contains (span redaction, metric attribute allowlist) | `backend/app/observability/privacy.py` |
| Console logging and the `app` logger | `backend/app/observability/logs.py` |
| Settings and the resource | `backend/app/core/config.py` (`OTEL_*`, `resource_attributes()`) |
| Collector configuration | `deploy/observability/otel-collector.yaml` |
| Opt-in Compose overlay (Collector + telemetry on) | `compose.observability.yaml` |
| End-to-end check | `backend/observability_smoke/` (`make observability`, CI job "Observability (OpenTelemetry)") |

## Signals

### Traces

- **One server span per HTTP request**, from `opentelemetry-instrumentation-fastapi`. It is named
  after the method and the **route template**, such as `GET /api/transactions/{transaction_id}`.
  It never uses the path, so `/api/transactions/123` and `/api/transactions/456` get the same
  name.
- **Attributes** follow the current HTTP semantic conventions:
  - `http.request.method`, `http.route`, `http.response.status_code` and `url.scheme`;
  - `url.path`, `network.protocol.version`, `server.address` and `server.port`.
  - The duration is the span's start and end times.
  - The app opts into these conventions itself (`OTEL_SEMCONV_STABILITY_OPT_IN=http`). The older
    ones would put the client's `Host` header on every metric.
- **Unhandled errors:** the span has status `ERROR`, `error.type` (`500`) and an `exception` event
  with the exception's **type only**. The same request also logs an `ERROR` record naming the
  type and the route. The message and stack trace stay in the server's own log (Uvicorn prints
  the traceback) and are never exported (see the data policy).
- **Not traced:** `/api/health`, `/api/health/ready` and `/api/meta`.
  - Docker, Render, the deploy gateway and the promotion workflow poll these probes all day, and
    their spans would drown out real traffic.
  - The exclusion matches only these exact paths, and covers their HTTP metrics as well.
- **No child spans:** the ASGI `receive` and `send` spans are left out. There is one span per
  request.
- **Outbound HTTP isn't instrumented.** The API makes no outbound HTTP calls (the AI provider is
  the fake one), so `opentelemetry-instrumentation-httpx` isn't installed. Add it when a real
  provider calls out, after checking that it records no URLs with keys, and no headers.

### Metrics

HTTP server metrics come from the same instrumentation:

| Metric | Unit | Attributes |
|---|---|---|
| `http.server.request.duration` (histogram) | s | `http.request.method`, `http.route`, `http.response.status_code`, `url.scheme`, `network.protocol.version`, `error.type` on failures |
| `http.server.active_requests` | `{request}` | `http.request.method`, `url.scheme` |
| `http.server.request.body.size`, `http.server.response.body.size` | By | as for the duration |

- **Bounded attributes only.** A view (`privacy.HTTP_METRIC_ATTRIBUTES`) keeps HTTP metrics to
  the bounded attributes above, whatever the instrumentation adds:
  - `http.route` is always a template;
  - unknown methods become `_OTHER`;
  - a path that matches no route has no `http.route` at all.
- **Never a metric attribute:** a user ID, an email address, a transaction's description, an
  amount, a raw URL, a query string, a client address or a trace ID.
- **Exemplars:** histogram points can carry exemplars, a sample trace ID and span ID that link
  a point to one of its traces. They're samples, not attributes, so they don't add series.
- **Not yet:** business metrics (transactions created, AI parsing results, KPIs) are the next
  issue.
- Metrics don't depend on trace sampling. They're exported every 60 s by default
  (`OTEL_METRIC_EXPORT_INTERVAL`), and every 5 s in the local overlay.

### Logs

- **The API is still Python's standard `logging`.** Loggers under `app.*`
  (`logging.getLogger(__name__)` in `backend/app/`) go to the console. With telemetry on, they
  also go over OTLP through the OpenTelemetry logging handler
  (`opentelemetry-instrumentation-logging`). The SDK's own handler is deprecated.
- **What it logs:**

  | Log | Level |
  |---|---|
  | Startup (environment, version, telemetry on or off) | INFO |
  | Account created | INFO |
  | Sign-in refused (no email) | WARNING |
  | Unhandled error: exception type, method and route template only | ERROR |
- **Trace context:** a record logged during a request carries that request's trace ID and span
  ID, in OTLP and on the console line (`… trace_id=… span_id=…`).
- **What gets exported, and what doesn't:**
  - INFO and up, from `app.*` loggers only.
  - Not Uvicorn's access log, which has client addresses and full URLs; the spans already
    describe every request.
  - Not SQLAlchemy.
  - Not OpenTelemetry's own loggers: an export failure is logged by `opentelemetry.*` and can
    never be exported in turn. The handler also guards against re-entrant calls.
- **One handler, ever:** the setup runs once per process, so a second `create_app()` adds no
  second handler and no record is exported twice.
- Logs don't depend on trace sampling. A record from an unsampled request is still exported,
  with its trace ID.

## Resource: the same identity on every signal

Every span, metric and log record of a process carries one resource, built from
`Settings.resource_attributes()`. The same code serves `GET /api/meta`.

| Attribute | Value |
|---|---|
| `service.name` | `spendwise-api` |
| `service.version` | the exact commit (`APP_VERSION`, else Render's `RENDER_GIT_COMMIT`). Left out when unknown, never guessed. |
| `deployment.environment.name` | `APP_ENV`: `local`, `test`, `development` or `production` |

- **Current semantic conventions.** The deprecated `deployment.environment` isn't used.
- **Automatic attributes:** the SDK adds `telemetry.sdk.*` and a random `service.instance.id`.
- **`OTEL_RESOURCE_ATTRIBUTES`** can add attributes (a region, for example). Neither it nor
  `OTEL_SERVICE_NAME` can replace the three above.

## Configuration

Off (the default, and how development and production run today), telemetry needs **no other
setting**: no endpoint, no ratio, nothing to add to Render or AWS.

| Variable | Default | Meaning |
|---|---|---|
| `OTEL_ENABLED` | `false` | Turns telemetry on. Off, nothing is exported, no exporter or thread starts, and the tracing and metrics API calls do nothing. |
| `OTEL_SDK_DISABLED` | `false` | OpenTelemetry's standard switch. `true` turns telemetry off whatever `OTEL_ENABLED` says. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | none | The base URL of the Collector's OTLP/HTTP receiver, e.g. `http://otel-collector:4318`. Required when enabled. The signal paths `/v1/traces`, `/v1/metrics` and `/v1/logs` are added to it. `http(s)` only, with no credentials, query string or fragment. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | The only value accepted: no gRPC exporter is installed. |
| `OTEL_TRACES_SAMPLE_RATIO` | `1.0` locally and in tests | The share of new traces kept, from `0.0` to `1.0`. `development` and `production` **must set it** when telemetry is on, so a deployment can't keep every trace by default. |

- **Bad configuration stops startup** with a clear error that doesn't repeat the value. That
  covers a malformed switch, an endpoint that isn't an http(s) URL or contains credentials, a
  protocol other than `http/protobuf`, and a ratio outside 0 to 1 (`nan` included).
- **Standard SDK variables that still apply:** `OTEL_METRIC_EXPORT_INTERVAL`, `OTEL_BSP_*`,
  `OTEL_BLRP_*`, `OTEL_RESOURCE_ATTRIBUTES`, and `OTEL_EXPORTER_OTLP_HEADERS` (headers for a
  receiver that needs them).
- **Standard variables the app sets itself:** the sampler (`OTEL_TRACES_SAMPLER*`), the service
  name, the excluded URLs, the export timeout (5 s) and `OTEL_SEMCONV_STABILITY_OPT_IN`.

## Sampling

- **Parent-based, by trace-ID ratio** (`ParentBased(TraceIdRatioBased(ratio))`). A request
  starts a trace with probability `ratio`, and spans inside it follow that decision.
- **A caller can't decide sampling.** The ratio also applies when a client sends a `traceparent`
  header, whatever its sampled flag says, so an outside caller can't make SpendWise keep or drop
  traces.
- **Metrics and logs are never sampled.**
- **Locally:** `1.0`. **Deployed:** a fraction, chosen when telemetry is turned on (`0.1` is a
  reasonable start).

## Data policy (privacy)

SpendWise is a finance application, so telemetry describes the **service**, never the people
using it or their money.

| Never in any span, metric or log | How it is kept out |
|---|---|
| Request and response bodies: passwords, transactions, descriptions, amounts | The instrumentation records no bodies. SpendWise's logs never include submitted values: no email in the sign-in logs, and only the exception type in the error log. |
| Headers: `Authorization`, `Cookie`, `Set-Cookie`, session and deploy tokens | No header capture is configured. Header attributes (`http.request.header.*`, `http.response.header.*`) are dropped from every span, even if the `OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*` variables ask for them. |
| The client's IP address, port and browser; query strings | `client.address`, `client.port`, `user_agent.original`, `url.query`, `url.full` (and their older names) are dropped from every span before export (`privacy.RedactingSpanProcessor`). |
| Exception messages and stack traces, e.g. PostgreSQL's `DETAIL: Key (user_id, name, type)=(1, <category name>, expense) already exists` when the same category is created twice at once | Exception events keep `exception.type` (and `exception.escaped`) only, and a failed span's status has no description (`privacy.redact`). SpendWise's error log names the exception type, never its message, and app code never logs `exc_info` (a test checks). |
| SQL parameter values | The database engine runs with `hide_parameters=True`, so not even the server log's tracebacks show them. |
| Secrets or free text in URL paths | `url.path` stays, as the HTTP conventions require, but every API path parameter is an integer ID, the frontend routes are fixed names, and query strings are dropped (a test checks the OpenAPI spec). Metrics use `http.route`. |
| Database URLs, API keys, OIDC tokens | Never logged. The OTLP endpoint can't contain credentials. The resource holds only the three attributes above. |
| User-controlled text as a metric attribute | The HTTP metric attribute allowlist. Future metrics may only use bounded values (`get_meter()`'s docstring). |

- **Log `extra` fields become attributes.** Fields passed to a log call
  (`log.info(..., extra={...})`) are exported as log attributes, so they follow the same rules.
- **Trace context is fine.** Trace IDs and span IDs are random and identify a request, not a
  person.
- **Tested in three places:**
  - `tests/integration/test_telemetry.py` sends a password, an email, a session cookie, a bearer
    token, a transaction description, an amount, a query string and a user agent, with header
    capture requested, then searches everything exported for them.
  - The smoke test does the same with everything the Collector printed.
  - `tests/unit/test_telemetry_settings.py` covers the redaction rules.

## Failure behaviour

- **Telemetry never delays or fails a request.** Spans, metrics and logs are queued in memory
  and exported by background threads.
- **A missing or slow Collector costs at most 5 s per export,** retries included. The data is
  then dropped, and requests are unaffected:
  - the smoke test stops the Collector, checks that requests still answer in under 2 s and that
    the app stays healthy, then starts the Collector and checks that export resumes without
    restarting the app;
  - `test_an_unreachable_collector_never_breaks_a_request` does the same against a closed port.
- **Shutdown is bounded.** When the server stops, the app's lifespan flushes and stops all three
  providers, and they give up after about 5 s each if nothing answers. An `atexit` hook covers
  a process that never ran its lifespan.
- **Nothing recurses.** Export errors are logged by OpenTelemetry's own loggers, which aren't
  exported.
- **Telemetry off means no side effects:** no exporter, no thread, no network, no global
  provider and no extra log handler.

## Running it locally

```bash
docker compose -f compose.yaml -f compose.override.yaml -f compose.observability.yaml up -d --build
open http://localhost:8000          # use the app
docker compose -f compose.yaml -f compose.override.yaml -f compose.observability.yaml logs -f otel-collector
```

The Collector prints a `ResourceSpans`, `ResourceMetrics` or `ResourceLog` block for each
export. The app's console shows trace IDs next to its own log lines. `docker compose up` without
the overlay is unchanged and sends no telemetry.

The Collector also counts what it accepted and exported. It is reachable only on the internal
network, so read the counts through the app container:

```bash
docker compose -f compose.yaml -f compose.override.yaml -f compose.observability.yaml exec app \
  python -c "import urllib.request; print(urllib.request.urlopen('http://otel-collector:8888/metrics').read().decode())" \
  | grep -E '^otelcol_(receiver_accepted|exporter_sent)'
```

- **What's published:** nothing about the Collector. Its receiver listens only on the internal
  `telemetry` network, which has no route to the outside. The app keeps its usual
  `127.0.0.1:8000`.
- **Limits:** the Collector container runs read-only, with 256 MiB of memory (`memory_limiter`
  stays below that).
- **Running the backend from source:** point `OTEL_EXPORTER_OTLP_ENDPOINT` at a Collector of your
  own. The Compose one isn't reachable from the host.

## Verification

```bash
make observability                               # or: cd backend && uv run pytest observability_smoke
cd backend && uv run pytest tests/unit/test_telemetry_settings.py tests/integration/test_telemetry.py \
  tests/unit/test_observability_config.py tests/unit/test_collector_output.py tests/unit/test_logging_setup.py
```

`make observability` builds the image and starts PostgreSQL, the app and the Collector (project
`spendwise-otel`, port 18200, removed afterwards). It then sends real traffic: the probes, a
sign-up, a transaction, reads, a refused sign-in, a 404 and a sign-out. It polls the Collector's
output, with a deadline and no fixed sleeps, and requires:

- **traces:** the requests' spans, named after route templates, and none for the probes;
- **metrics:** `http.server.request.duration` with route templates and only bounded attributes;
- **logs:** "Sign-in refused" with the trace ID and span ID of the sign-in request's span, and
  "Account created" with the sign-up's trace;
- **resource:** `service.name=spendwise-api`, `deployment.environment.name=local` and
  `service.version`, the stack's `APP_VERSION`, on every signal;
- **counters:** the Collector's own counts of accepted and exported spans, metric points and log
  records are all above zero, with none refused or failed;
- **privacy:** none of the email, passwords, session cookie, description, amount, query string,
  user agent or database password appears anywhere in what the Collector received;
- **failure:** with the Collector stopped, the app keeps serving, and once it's back, telemetry
  resumes.

In CI the job **Observability (OpenTelemetry)** runs `make observability` for every pull request
and every push to `main`. "All checks passed" requires it, and so, through that check, does the
promotion workflow. The job has the workflow's read-only token only. On failure it uploads the
run's container logs, Collector output included.

## Turning it on in development or production (not done here)

Neither environment's configuration changes in this step, and nothing sends telemetry there.
When it's time:

- **Production (AWS):**
  - add the Collector service and the internal network from `compose.observability.yaml` to
    `deploy/aws/compose.aws.yaml`;
  - set `OTEL_ENABLED=true`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` and
    `OTEL_TRACES_SAMPLE_RATIO` (for example `0.1`) on the app;
  - give the Collector an exporter to the chosen backend, with its credentials from the
    instance's secrets file, never from Git;
  - check the instance's memory: a t3.micro has 1 GiB.
- **Development (Render):** a free web service can't run a Collector next to it. Either send
  OTLP to a hosted Collector, or to the backend's OTLP gateway, with
  `OTEL_EXPORTER_OTLP_HEADERS` from a Render secret. Either way, set `OTEL_TRACES_SAMPLE_RATIO`.

## Next: Grafana

The app sends OTLP to "the Collector" and knows nothing about what's behind it. The Grafana phase
changes only `deploy/observability/otel-collector.yaml`:

- **traces:** add an exporter to Tempo (or Grafana Cloud's OTLP endpoint);
- **metrics:** Mimir or Prometheus (`prometheus_remote_write`, or `otlp_http`);
- **logs:** Loki (`otlp_http` to Loki's OTLP endpoint);
- in each pipeline, put the new exporter next to (or in place of) `debug`, and set `debug` to
  `verbosity: basic`.

Application code that adds its own telemetry uses the public API in `app.observability`, never the
SDK:

```python
from app.observability import get_meter, get_tracer

meter = get_meter(__name__)
transactions_created = meter.create_counter("spendwise.transactions.created")
transactions_created.add(1, {"transaction.type": "expense"})   # bounded values only

with get_tracer(__name__).start_as_current_span("categorize"):
    ...
```

Both work whether telemetry is on or off. `Settings.resource_attributes()` and
`app.observability.build_resource()` are the single source of the service's identity.
