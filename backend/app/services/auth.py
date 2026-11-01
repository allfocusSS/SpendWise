"""Accounts and sign-in sessions. Passwords are only ever passed to app.core.security."""

from datetime import timedelta

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import BusinessRuleError, ConflictError
from app.core.security import (
    burn_password_check,
    hash_password,
    hash_session_token,
    needs_rehash,
    new_session_token,
    verify_password,
)
from app.models import User, UserSession
from app.models.base import utc_now
from app.seed import seed_default_categories

EMAIL_TAKEN = "An account with this email already exists"


def normalize_email(email: str) -> str | None:
    """Canonical form used for storage and lookup (case-insensitive), or None if invalid."""
    try:
        return validate_email(email.strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None


def create_user(db: Session, email: str, password: str) -> User:
    """A new account with its own copy of the default categories."""
    normalized = normalize_email(email)
    if normalized is None:  # the request schema already validated it; this is a safety net
        raise BusinessRuleError("Invalid email address")
    if db.scalar(select(User.id).where(User.email == normalized)) is not None:
        raise ConflictError(EMAIL_TAKEN)

    user = User(email=normalized, password_hash=hash_password(password))
    db.add(user)
    try:
        db.flush()
        seed_default_categories(db, user.id)
        db.commit()
    except IntegrityError:
        # Two signups for the same email at the same moment: the unique constraint decides.
        db.rollback()
        raise ConflictError(EMAIL_TAKEN) from None
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    """The user for these credentials, or None. Unknown email and wrong password look the same."""
    normalized = normalize_email(email)
    user = db.scalar(select(User).where(User.email == normalized)) if normalized else None
    if user is None:
        burn_password_check(password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
        db.commit()
    return user


def start_session(db: Session, user: User) -> str:
    """Create a session and return its token (for the cookie). Expired sessions are tidied."""
    now = utc_now()
    db.execute(
        delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at < now)
    )
    token = new_session_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=now + timedelta(days=get_settings().session_ttl_days),
        )
    )
    db.commit()
    return token


def user_for_session_token(db: Session, token: str) -> User | None:
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_session_token(token))
    )
    if session is None:
        return None
    if session.expires_at <= utc_now():
        db.delete(session)
        db.commit()
        return None
    return db.get(User, session.user_id)


def end_session(db: Session, token: str) -> None:
    db.execute(delete(UserSession).where(UserSession.token_hash == hash_session_token(token)))
    db.commit()
