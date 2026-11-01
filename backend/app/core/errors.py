"""Domain errors raised by services, and the handlers that turn them into HTTP responses.

Services never import FastAPI; they raise these errors and the API layer picks the status code.
"""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Validation errors from these routes never echo what was submitted (it may be a password).
SENSITIVE_PATH_PREFIX = "/api/auth/"


class DomainError(Exception):
    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    status_code = 409


class BusinessRuleError(DomainError):
    """Input is well-formed but breaks a rule (e.g. unknown category, type mismatch)."""

    status_code = 422


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        if not request.url.path.startswith(SENSITIVE_PATH_PREFIX):
            return await request_validation_exception_handler(request, exc)
        # Same shape as FastAPI's 422, minus "input" (the submitted value) and "ctx" (which can
        # include e.g. the password's length).
        errors = [
            {key: value for key, value in error.items() if key not in ("input", "ctx")}
            for error in jsonable_encoder(exc.errors())
        ]
        return JSONResponse(status_code=422, content={"detail": errors})
