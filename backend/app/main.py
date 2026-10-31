from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.api.routes import analytics, categories, health, transactions
from app.core.config import get_settings
from app.core.errors import register_error_handlers


def _operation_id(route: APIRoute) -> str:
    # Use the function name (e.g. "list_transactions") as the OpenAPI operationId.
    return route.name


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="0.1.0",
        generate_unique_id_function=_operation_id,
    )
    register_error_handlers(app)
    for module in (health, categories, transactions, analytics):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()
