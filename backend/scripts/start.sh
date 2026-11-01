#!/bin/sh
# Production startup (the Docker image's CMD). Run from the backend directory.
#
# 1. Wait until PostgreSQL accepts connections (DB_WAIT_TIMEOUT seconds, default 60). Compose
#    already orders the services; platforms without ordering (e.g. Railway) rely on this.
# 2. Bring the schema up to date. Concurrent starts take turns (a PostgreSQL advisory lock in
#    alembic/env.py); migrations never drop user data. Default categories are created at signup.
# 3. Replace this shell with Uvicorn so it receives SIGTERM directly. It listens on $PORT when
#    the platform provides one (Railway does), otherwise 8000, and trusts X-Forwarded-Proto/-For
#    from FORWARDED_ALLOW_IPS (default: any) so HTTPS behind a proxy is recognised.
set -eu

python -m app.core.wait_for_db
alembic upgrade head
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}"
