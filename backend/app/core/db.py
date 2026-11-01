from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(database_url: str, **kwargs) -> Engine:
    """Create an engine for SQLite (local, tests) or PostgreSQL (production)."""
    is_sqlite = database_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}
    if not is_sqlite:
        # PostgreSQL connections can be closed by the server (restart, idle timeout); check each
        # pooled connection before use instead of failing the next request.
        kwargs.setdefault("pool_pre_ping", True)
    engine = create_engine(database_url, connect_args=connect_args, **kwargs)

    if is_sqlite:
        # SQLite ignores foreign keys unless this is turned on for every connection.
        @event.listens_for(engine, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


engine = build_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with SessionLocal() as session:
        yield session
