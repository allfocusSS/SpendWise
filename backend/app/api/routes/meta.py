from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from app.core.config import AppEnv, Settings, get_settings

router = APIRouter(prefix="/meta", tags=["meta"])


class MetaResponse(BaseModel):
    environment: AppEnv = Field(description="APP_ENV of this deployment.")
    version: str | None = Field(
        description="The exact Git commit this deployment runs (40 lowercase hex characters), "
        "or null if the deployment did not supply one.",
        pattern=r"^[0-9a-f]{40}$",
    )


@router.get("", response_model=MetaResponse)
def meta(response: Response, settings: Annotated[Settings, Depends(get_settings)]) -> MetaResponse:
    """Which environment this is and which commit it runs; public, like the health checks.

    The promotion workflow waits for development to report a commit before deploying it to
    production, then checks production reports it. Nothing else is exposed: no hostnames,
    database details, infrastructure IDs or secrets.
    """
    # A deploy changes the answer; no cache may keep the old one.
    response.headers["Cache-Control"] = "no-store"
    return MetaResponse(environment=settings.app_env, version=settings.version)
