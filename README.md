# SpendWise

AI-powered personal finance manager (MVP). Single currency: KZT (₸).

- **Backend:** FastAPI + SQLAlchemy (SQLite locally, PostgreSQL in Docker)
- **Frontend:** React + TypeScript + Tailwind CSS (Vite)
- **AI:** Anthropic SDK behind a provider interface; a fake provider is the default so the app runs without an API key. All financial calculations happen in Python, never in the AI.

> ⚠️ No authentication in the local MVP. Do not deploy publicly until authentication is implemented.

## Prerequisites

- Python 3.13 + [uv](https://docs.astral.sh/uv/)
- Node.js 24

## Local development

```bash
# Backend — http://localhost:8000 (API docs at /docs)
cd backend
cp ../.env.example .env
uv sync
uv run alembic upgrade head      # create/upgrade the database schema
uv run python -m app.seed        # add default categories (only if there are none)
uv run uvicorn app.main:app --reload

# Frontend — http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

## Money and API conventions

- Amounts are **positive integers in cents (tiyn)**: `250000` = 2 500.00 ₸. The `type` field (`income` / `expense`) gives the direction. Floats and numeric strings are rejected.
- All totals, balances, percentages and trends are calculated by the backend.
- Errors return `{"detail": ...}`; `detail` is a string for 404/409/422 business errors and a list for request validation errors.

## Database migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"   # after changing models
uv run alembic upgrade head
```

## OpenAPI spec

The spec is committed at `openapi/openapi.json`. After changing the API:

```bash
cd backend && uv run python scripts/export_openapi.py
```

CI fails if the committed spec is out of date.

## Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npm run lint && npm run build
```
