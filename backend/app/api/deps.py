"""Dependencies shared by the API routes: the database session and the signed-in user."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import User
from app.schemas.common import ErrorResponse
from app.services import auth as auth_service

SESSION_COOKIE = "spendwise_session"

# Declares the cookie in OpenAPI (so /docs shows which routes need a session); auto_error=False
# so a missing cookie gets the same 401 body as an invalid one.
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    auto_error=False,
    description="HttpOnly session cookie set by POST /api/auth/signup and /api/auth/login.",
)

DbSession = Annotated[Session, Depends(get_db)]
SessionToken = Annotated[str | None, Depends(session_cookie)]

NOT_AUTHENTICATED = "Not authenticated"
UNAUTHORIZED = {401: {"model": ErrorResponse}}


def get_current_user(db: DbSession, token: SessionToken) -> User:
    user = auth_service.user_for_session_token(db, token) if token else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=NOT_AUTHENTICATED)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
