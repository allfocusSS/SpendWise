# Developer shortcuts. Each target is also documented in README.md as a plain command.

.PHONY: integration e2e observability dashboard

# Integration tests against the real Docker Compose stack (built frontend, FastAPI, PostgreSQL).
# Needs Docker (with Compose v2) and uv. Builds and starts its own isolated stack on port 18000,
# then removes it, volume included. Your local `spendwise` stack is not touched.
# Extra pytest arguments: make integration ARGS="-k analytics -x"
integration:
	cd backend && uv run pytest integration $(ARGS)

# End-to-end tests in a real browser (Playwright, headless Chromium) against the real Docker
# Compose stack. Needs Docker, uv and Node; installs the Chromium build Playwright uses if it is
# missing. Builds and starts its own isolated stack on port 18100, removes it afterwards.
# Extra Playwright arguments: make e2e ARGS="--project=mobile-chromium --grep Analytics"
e2e:
	cd frontend && npx playwright install chromium && npx playwright test $(ARGS)

# OpenTelemetry end to end: the same stack plus the Collector (compose.observability.yaml), real
# traffic, then checks that traces, metrics and logs all reached the Collector, with the right
# resource and nothing sensitive in them. Needs Docker and uv; its own stack on port 18200,
# removed afterwards. Extra pytest arguments: make observability ARGS="-x"
observability:
	cd backend && uv run pytest observability_smoke $(ARGS)

# The dashboard, end to end: the same stack plus Grafana's LGTM image (compose.dashboard.yaml).
# Real traffic, including controlled failures, then checks that SpendWise's metrics reached
# Prometheus with exact counts, that the dashboard is provisioned and its queries work, and that
# logs reach Loki and traces Tempo. Needs Docker and uv (the image is about 1 GB); its own stack
# (app on 18300, Grafana on 127.0.0.1:13000), removed afterwards. Extra pytest arguments:
# make dashboard ARGS="-x"
dashboard:
	cd backend && uv run pytest dashboard_smoke $(ARGS)
