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
uv run uvicorn app.main:app --reload

# Frontend — http://localhost:5173 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

## Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npm run lint && npm run build
```
