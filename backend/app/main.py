import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.routes import analytics, auth, categories, health, meta, transactions
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.frontend import mount_frontend
from app.observability import (
    configure_logging,
    instrument_app,
    setup_telemetry,
    shutdown_telemetry,
)
from app.observability import metrics as app_metrics

log = logging.getLogger(__name__)


def _operation_id(route: APIRoute) -> str:
    # Use the function name (e.g. "list_transactions") as the OpenAPI operationId.
    return route.name


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info(
        "SpendWise API started: environment %s, version %s, telemetry %s",
        settings.app_env,
        settings.version or "unknown",
        "on" if settings.telemetry_enabled else "off",
    )
    yield
    # Export what is still buffered before the process exits (bounded; nothing when off).
    shutdown_telemetry()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    # Once per process, and only with OTEL_ENABLED=true (docs/observability.md).
    telemetry = setup_telemetry(settings)
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        generate_unique_id_function=_operation_id,
        lifespan=_lifespan,
    )
    register_error_handlers(app)
    for module in (health, meta, auth, categories, transactions, analytics):
        app.include_router(module.router, prefix="/api")
    if settings.frontend_dist is not None:
        # Production image: the built React app is served from the same origin as the API.
        mount_frontend(app, settings.frontend_dist)
    if telemetry is not None:
        instrument_app(app, telemetry)
        app_metrics.initialize(settings.ai_provider)  # zero series for the dashboard (metrics.py)
    return app


app = create_app()
