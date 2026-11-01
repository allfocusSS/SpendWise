#!/bin/sh
# Production startup (the Docker image's CMD). Run from the backend directory.
#
# 1. Bring the database schema up to date. (Default categories are created per user at signup.)
# 2. Replace this shell with Uvicorn so it receives SIGTERM from `docker stop` directly.
set -eu

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
