"""Wait until the database accepts connections. Run by scripts/start.sh before migrations.

Docker Compose starts the app only after PostgreSQL is healthy, but not every platform orders
services (Railway, for example, has no depends_on). This keeps trying `SELECT 1` against
DATABASE_URL for DB_WAIT_TIMEOUT seconds (default 60) and exits non-zero if the database never
answers. The URL is never printed: it can contain the password.

  python -m app.core.wait_for_db
"""

import os
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.db import build_engine

RETRY_SECONDS = 2


def wait_for_database(timeout: float, interval: float = RETRY_SECONDS) -> bool:
    engine = build_engine(get_settings().database_url, pool_pre_ping=False)
    deadline = time.monotonic() + timeout
    attempt = 0
    try:
        while True:
            attempt += 1
            try:
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                print(f"Database is ready (attempt {attempt}).", flush=True)
                return True
            except OperationalError as error:
                # The driver's first line names the problem (refused, unknown host, bad password)
                # without the connection URL.
                reason = str(error.orig).strip().splitlines()[0] if error.orig else "unavailable"
                if time.monotonic() + interval > deadline:
                    print(f"Database still unavailable after {timeout:.0f}s: {reason}", flush=True)
                    return False
                print(f"Waiting for the database (attempt {attempt}): {reason}", flush=True)
                time.sleep(interval)
    finally:
        engine.dispose()


def main() -> int:
    timeout = float(os.environ.get("DB_WAIT_TIMEOUT", "60"))
    return 0 if wait_for_database(timeout) else 1


if __name__ == "__main__":
    sys.exit(main())
