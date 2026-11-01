#!/bin/sh
# Production startup (the Docker image's CMD). Run from the backend directory.
#
# 1. Bring the database schema up to date.
# 2. Add the default categories, only if the categories table is empty (safe on every start).
# 3. Replace this shell with Uvicorn so it receives SIGTERM from `docker stop` directly.
set -eu

alembic upgrade head
python -m app.seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
