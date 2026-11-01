from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UTCDateTime, utc_now


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Stored lower-cased (see app.services.auth.normalize_email), so uniqueness ignores case.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    # Argon2id hash in PHC format ("$argon2id$v=19$..."). Never the password itself.
    password_hash: Mapped[str] = mapped_column(String(255))


class UserSession(Base):
    """A signed-in browser. The cookie holds a random token; only its SHA-256 is stored here,
    so a copy of the database cannot be used to sign in."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
