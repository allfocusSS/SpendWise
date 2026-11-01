# SpendWise

AI-powered personal finance manager (MVP). Single currency: KZT (₸).

- **Backend:** FastAPI + SQLAlchemy + Alembic (SQLite for local development and tests, PostgreSQL in production)
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

## PostgreSQL

SQLite (the default in `.env.example`) needs no setup and is fine for local development.
Production and the Docker image use PostgreSQL, through the psycopg 3 driver. The connection
comes only from `DATABASE_URL`; no credentials are stored in the code or the image.

### Run PostgreSQL locally

With Docker, as below (tested with PostgreSQL 18), or any local PostgreSQL install such as Homebrew `postgresql@18`:

```bash
export SPENDWISE_DB_PASSWORD="$(openssl rand -hex 16)"   # choose your own; never commit it
docker network create spendwise                          # lets the app container reach it later
docker run -d --name spendwise-postgres --network spendwise \
  -e POSTGRES_USER=spendwise -e POSTGRES_PASSWORD="$SPENDWISE_DB_PASSWORD" -e POSTGRES_DB=spendwise \
  -p 127.0.0.1:5432:5432 -v spendwise-pgdata:/var/lib/postgresql postgres:18
```

Point the backend at it in `backend/.env`, then migrate, seed and run as usual:

```bash
# backend/.env
DATABASE_URL=postgresql+psycopg://spendwise:<password>@localhost:5432/spendwise

cd backend
uv run alembic upgrade head
uv run python -m app.seed
uv run uvicorn app.main:app --reload
```

- `postgres://` and `postgresql://` URLs are accepted and use psycopg 3 automatically.
- URL-encode special characters in the password (`@` → `%40`, `/` → `%2F`, `%` → `%25`).
- `ENVIRONMENT=production` refuses to start unless `DATABASE_URL` is PostgreSQL.
- Settings validation errors never print the URL, and `repr(settings)` hides it.
- There is no tool to copy data from an existing SQLite file; a new PostgreSQL database starts
  empty (plus the default categories).

### Run the tests on PostgreSQL

Tests use a fresh in-memory SQLite database unless `TEST_DATABASE_URL` is set:

```bash
docker exec spendwise-postgres createdb -U spendwise spendwise_test
cd backend
TEST_DATABASE_URL=postgresql+psycopg://spendwise:<password>@localhost:5432/spendwise_test uv run pytest
```

Every test creates and drops all tables, so the database name must contain `test`. Never point
it at a database with real data. CI runs the suite on both SQLite and PostgreSQL.

## Docker (single production container)

The `Dockerfile` at the repo root builds one image: Node builds the React app to static files,
and FastAPI serves them alongside the API on port 8000.

The image needs a PostgreSQL `DATABASE_URL`. With the `spendwise-postgres` container from
[Run PostgreSQL locally](#run-postgresql-locally) on the `spendwise` network:

```bash
docker build -t spendwise .
docker run --rm --network spendwise -p 127.0.0.1:8000:8000 \
  -e DATABASE_URL="postgresql+psycopg://spendwise:$SPENDWISE_DB_PASSWORD@spendwise-postgres:5432/spendwise" \
  spendwise
# http://127.0.0.1:8000  (API under /api, docs at /docs)
```

- On start the container runs `alembic upgrade head`, seeds the default categories (only when the
  categories table is empty), then starts Uvicorn on `0.0.0.0:8000` (`backend/scripts/start.sh`).
- The image sets `ENVIRONMENT=production` and has no `DATABASE_URL` default: without a PostgreSQL
  URL it exits at once with an error. If PostgreSQL is not reachable yet, the migration fails and
  the container exits; start the database first or add `--restart on-failure`.
- The backend serves the frontend only when `FRONTEND_DIST` is set (the image sets it). Client
  routes such as `/transactions` return `index.html`, so a refresh works; unknown `/api/...` paths
  still return JSON 404s.
- AI settings come from environment variables (`-e AI_PROVIDER=...`); no `.env` file is copied
  into the image.

> ⚠️ No authentication yet. Publish the port on `127.0.0.1` only, as above, and do not deploy the
> image publicly.

## Money and API conventions

- Amounts are **positive integers in cents (tiyn)**: `250000` = 2 500.00 ₸. The `type` field (`income` / `expense`) gives the direction. Floats and numeric strings are rejected.
- All totals, balances, percentages and trends are calculated by the backend.
- The frontend converts typed tenge to tiyn with string parsing in `frontend/src/lib/money.ts` (`parseKztToTiyn`), never with floating-point multiplication, and enforces the same maximum as the backend (a test compares it with `openapi.json`).
- Errors return `{"detail": ...}`; `detail` is a string for 404/409/422 business errors and a list for request validation errors.

## AI providers

AI code lives in `backend/app/ai/`. Every provider implements the `AIProvider` protocol
(`provider.py`) with two methods: `parse_transaction` (free text → unsaved draft) and
`generate_insights` (backend-calculated summary → typed insight topics + optional advice).

| `AI_PROVIDER` | Behaviour |
|---|---|
| `fake` (default) | Deterministic keyword rules. No network, no API key. Same input → same output. |
| `anthropic` | Requires `ANTHROPIC_API_KEY`. Not implemented yet (Issue #2): AI features return HTTP 503 with a clear message; the rest of the app works. |

The value is case-insensitive; an unknown value stops the app at startup with a validation error.
`ANTHROPIC_API_KEY` is a `SecretStr`: it is masked in `repr()`, `model_dump()` and error messages.
Tests force `AI_PROVIDER=fake` before the app is imported, so local shell or `.env` values cannot
affect them.

### What the AI layer checks about money

**Transaction drafts.** Providers return the amount exactly as the user typed it (`amount_text`),
never a number. The fake provider leaves the amount empty, with a note, instead of guessing when:

- the format is ambiguous (`450,000`, `1,234,567`, `12.500`, `1.500,50`);
- thousands grouping is malformed (`12 34`, `2027 5000`) or uses a tab or several spaces;
- the text uses digits or numerals other than ASCII `0-9` (Arabic-Indic, fullwidth, `½`, `²`);
- several numbers could be the amount (`iphone 15 for 500000`, `500 tenge and 300 tenge`);
- a multiplier follows the amount (`1.5k`, `2к`, `300 тыс`, `5 млн`, `2.5 thousand`): it is never
  converted;
- the text mentions another currency (`$50`, `€40`, `50 USD`, `50 рублей`): there is no conversion;
- the text contains a calculation, range or percentage (`3000/2`, `1500-2000`, `2x1500`, `x2`,
  `10%`, or any symbol standing alone between two numbers: `1500 – 2000`);
- the amount is not standing alone. Within its space-separated word, only an opening bracket or
  quote, `₸` or a tenge word and a leading `-` may come before it, and only `₸` or a tenge word,
  a closing bracket or quote and sentence punctuation may come after it. Anything else (`1'500`,
  `1500–2000`, `3000∕2`, `iphone15`, an invisible character) means the amount is left empty. This
  is a structural rule, not a list of characters.

Accepted: `2500`, `2 500` (space, no-break, narrow no-break U+202F, thin U+2009 or figure U+2007
space between exact 3-digit groups), up to two decimals (`2 500,50`, `19.99`), and a currency word
before or after (`₸1500`, `1500 tenge`, `5000tg`). Converting `amount_text` to tiyn is a backend
step (Issue #2).

**Insights.** Providers do not write sentences that contain figures. They return a list of typed
topics (`overview`, `balance`, `top_category`, `expense_change`) with optional advice. The backend
(`app/ai/facts.py`):

- chooses the sentence from the actual figures: `balance` becomes `balance_surplus`,
  `balance_deficit` or `balance_even` by the sign of the backend balance; `expense_change` becomes
  `expense_increase`, `expense_decrease` or `expense_unchanged` by the rounded change. Providers
  cannot name these sentence ids;
- renders each sentence from a fixed template, so income, expenses, balance and shares always
  appear in their own roles;
- shows user-controlled category names in quotes, exactly as typed (minus invisible characters).

**Advice** is the only provider-written text. After removing invisible characters it is checked
both as written and after Unicode NFKC normalisation, and rejected if it contains any numeric
character (`5`, `½`, `Ⅻ`, `五`, `٤`), any currency symbol (Unicode category `Sc`), a percent or
per-mille marker, braces, or a word mixing Latin and Cyrillic letters. Best-effort word lists also
reject unit words (`tenge`, `теңге`, `тңг`, `tg`, `percent`, `пайыз`…), English/Russian/Kazakh
number words, uppercase Roman numerals, and direction claims (`saved`, `surplus`, `deficit`,
`increased`, "in the black", "went down"…).

**What is not guaranteed:**

- Advice can still make **wrong claims about direction** in words the lists do not cover. For
  example, "Your balance is negative.", "You spent more than you earned." or "Spending jumped
  this month." pass the checks even when the backend figures say the opposite. Advice can also be
  unhelpful or have the wrong tone ("Great job!" next to a deficit). The word lists cannot cover
  every phrasing or language. The backend-rendered sentences are always correct; until advice is
  restricted structurally (Issue #2), treat advice as unverified text.
- The fake parser cannot tell every modifier apart from ordinary words: a spaced Cyrillic "к"
  (`50 к`) is not treated as a multiplier because it is also the Russian word "to", and a number
  that looks like valid grouping (`bus 7 500 tenge`) is read as one amount. Drafts are always
  reviewed by the user before saving.
- Category names are user data and may contain digits; they are quoted, not removed.
- These checks run on provider output. Issue #2 must call `render_insights` on every provider
  result and decide what to show when a result is rejected.

### Follow-up work (tracked from the PR #13 review)

| Item | Planned for |
|---|---|
| L2: enforce the draft contract for every provider (amount text taken from the input, offered category id, type matches category) and convert `amount_text` to tiyn in the backend | Issue #2 |
| L4: fake parser matches keywords inside words ("parent" → rent, "income tax" → income); use whole-word matching and prefer the longest category name | Issue #2 |
| L5: partly addressed (several candidate numbers now produce a note instead of a guess; the amount is removed from the description by position). Remaining: years written next to an amount, relative dates beyond "yesterday" | Issue #2 |
| L6: document and test that providers turn SDK errors and timeouts into `AIUnavailableError` without leaking SDK details | Issue #2 |
| L7: show users a generic 503 message and log configuration details server-side only | Security hardening (Issue #9) |

## Database migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"   # after changing models
uv run alembic upgrade head
```

## OpenAPI spec

The spec is committed at `openapi/openapi.json`. After changing the API:

```bash
cd backend && uv run python scripts/export_openapi.py   # 1. export the spec
cd frontend && npm run generate:api                     # 2. regenerate src/api/schema.d.ts
```

CI fails if either the spec or the generated TypeScript types are out of date.

## Checks

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npm run lint && npm test && npm run build

# Optional: the backend suite on PostgreSQL (see "Run the tests on PostgreSQL")
cd backend && TEST_DATABASE_URL=postgresql+psycopg://... uv run pytest
```
