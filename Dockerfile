# syntax=docker/dockerfile:1

# SpendWise production image. The React app is built to static files and served by FastAPI,
# so one container serves the UI and the API (/api) on $PORT (default 8000). The database is
# PostgreSQL, passed in at run time (no credentials are baked into the image):
#
#   docker build -t spendwise .
#   docker run --rm -p 127.0.0.1:8000:8000 \
#     -e DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/spendwise spendwise
#
# The session cookie is Secure for every HTTPS request and in production; for plain HTTP on
# localhost add -e SESSION_COOKIE_SECURE=false. Deploying: see README, "Deploy to Railway".

# ---- 1. Frontend build (Node) ----
FROM node:24-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# `tsc -b` type-checks a test that imports the committed spec from ../openapi.
COPY openapi/ /build/openapi/
RUN npm run build

# ---- 2. Python dependencies (uv, locked, no dev tools) ----
FROM python:3.13-slim AS backend-deps
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# ---- 3. Runtime (Python + FastAPI) ----
FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    ENVIRONMENT=production \
    FRONTEND_DIST=/app/frontend_dist
# DATABASE_URL has no default: ENVIRONMENT=production refuses to start without a PostgreSQL URL.

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin spendwise
WORKDIR /app

COPY --from=backend-deps /app/.venv ./.venv
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY --chmod=0755 backend/scripts/start.sh ./start.sh
COPY --from=frontend /build/frontend/dist ./frontend_dist

USER spendwise
EXPOSE 8000

# Listens on $PORT if the platform sets one (Railway does), otherwise 8000; see start.sh.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT', '8000')}/api/health/ready\", timeout=4)"]

CMD ["./start.sh"]
