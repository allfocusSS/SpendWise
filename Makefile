# Developer shortcuts. Each target is also documented in README.md as a plain command.

.PHONY: integration

# Integration tests against the real Docker Compose stack (built frontend, FastAPI, PostgreSQL).
# Needs Docker (with Compose v2) and uv. Builds and starts its own isolated stack on port 18000,
# then removes it, volume included. Your local `spendwise` stack is not touched.
# Extra pytest arguments: make integration ARGS="-k analytics -x"
integration:
	cd backend && uv run pytest integration $(ARGS)
