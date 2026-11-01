# Developer shortcuts. Each target is also documented in README.md as a plain command.

.PHONY: integration e2e

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
