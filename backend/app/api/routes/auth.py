"""Sign up, log in, log out and "who am I". The session lives in an HttpOnly cookie.

Cookie: HttpOnly (not readable by JavaScript), SameSite=Lax (not sent on cross-site POST, PUT,
PATCH or DELETE requests), Path=/, Max-Age=SESSION_TTL_DAYS, and Secure for every HTTPS request
and in production (see Settings.secure_cookie). Every login or signup issues a new token and ends
the previous session.
"""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import (
    SESSION_COOKIE,
    UNAUTHORIZED,
    CurrentUser,
    DbSession,
    SessionToken,
)
from app.core.config import get_settings
from app.models import User
from app.schemas.auth import LoginRequest, SignupRequest, UserRead
from app.schemas.common import ErrorResponse
from app.services import auth as service

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "Invalid email or password"


def _cookie_options(request: Request) -> dict:
    # request.url.scheme is "https" for direct HTTPS and behind a trusted proxy that sends
    # X-Forwarded-Proto: https (Uvicorn's --proxy-headers, see scripts/start.sh).
    secure = get_settings().secure_cookie(request_is_https=request.url.scheme == "https")
    return {"httponly": True, "secure": secure, "samesite": "lax", "path": "/"}


def _sign_in(
    db: DbSession, request: Request, response: Response, user: User, old_token: str | None
) -> None:
    if old_token:
        service.end_session(db, old_token)
    token = service.start_session(db, user)
    max_age = get_settings().session_ttl_days * 24 * 60 * 60
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, **_cookie_options(request))


@router.post(
    "/signup",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
def signup(
    data: SignupRequest, request: Request, response: Response, db: DbSession, token: SessionToken
):
    """Create an account (with its own default categories) and sign in."""
    user = service.create_user(db, data.email, data.password)
    _sign_in(db, request, response, user, token)
    return user


@router.post("/login", response_model=UserRead, responses=UNAUTHORIZED)
def login(
    data: LoginRequest, request: Request, response: Response, db: DbSession, token: SessionToken
):
    user = service.authenticate(db, data.email, data.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_CREDENTIALS)
    _sign_in(db, request, response, user, token)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: DbSession, token: SessionToken) -> None:
    """End this session. Safe to call when not signed in."""
    if token:
        service.end_session(db, token)
    response.delete_cookie(SESSION_COOKIE, **_cookie_options(request))


@router.get("/me", response_model=UserRead, responses=UNAUTHORIZED)
def me(user: CurrentUser):
    return user
