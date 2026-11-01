# SpendWise

AI-powered personal finance manager (MVP). Single currency: KZT (₸).

- **Backend:** FastAPI + SQLAlchemy + Alembic (SQLite for local development and tests, PostgreSQL in production)
- **Frontend:** React + TypeScript + Tailwind CSS (Vite)
- **AI:** Anthropic SDK behind a provider interface; a fake provider is the default so the app runs without an API key. All financial calculations happen in Python, never in the AI.

Each person signs up with an email and password and sees only their own transactions, categories
and analytics (see [Accounts and security](#accounts-and-security)).

> ⚠️ Not deployed anywhere yet. Before a public deployment, also read
> [Before deploying](#before-deploying).

## Quick start (Docker Compose)

Runs the whole stack (PostgreSQL 18 + the app) with Docker only; no Python or Node needed:

```bash
docker compose up --build        # open http://localhost:8000 (API docs at /docs)
docker compose down              # stop; your data is kept
```

See [Docker Compose](#docker-compose) for configuration and how to reset the database.

## Prerequisites

For development without Docker:

- Python 3.13 + [uv](https://docs.astral.sh/uv/)
- Node.js 24

## Local development

```bash
# Backend — http://localhost:8000 (API docs at /docs)
cd backend
cp ../.env.example .env
uv sync
uv run alembic upgrade head      # create/upgrade the database schema
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

Point the backend at it in `backend/.env`, then migrate and run as usual:

```bash
# backend/.env
DATABASE_URL=postgresql+psycopg://spendwise:<password>@localhost:5432/spendwise

cd backend
uv run alembic upgrade head
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

## Docker Compose

`compose.yaml` runs two services on a private Compose network:

| Service | What it is | Reachable from your machine |
|---|---|---|
| `db` | `postgres:18`, data in the named volume `pgdata` | No (port not published) |
| `app` | the production image built from `Dockerfile` (UI + API) | `http://localhost:8000` (127.0.0.1 only) |

```bash
docker compose up --build        # build and start in the foreground (Ctrl+C stops it)
docker compose up --build -d     # or in the background
docker compose logs -f app       # follow the app logs
docker compose ps                # status and health
docker compose down              # stop and remove the containers; the database volume is kept
```

**Startup order.** `db` is healthy once `pg_isready` succeeds. Only then does Compose start `app`,
which runs `alembic upgrade head` and starts Uvicorn (default categories are created per account
at signup). `app` is healthy once `GET /api/health/ready` (the image's own health check)
reaches the database. Both services use `restart: unless-stopped`: they restart after a crash or
a Docker restart, but stay down after `docker compose stop` or `down`. If `db` is restarted with
Compose, `app` is restarted after it.

**Persistence.** Data lives in the Docker volume `spendwise_pgdata` and survives
`docker compose down` and `up`, rebuilds and restarts. To delete the local database completely
and start again from an empty one:

```bash
docker compose down -v           # removes the containers AND the spendwise_pgdata volume
```

**Configuration.** Everything has a local-development default, so no setup is needed. To change
a value, put it in a `.env` file at the repo root (it is git-ignored; `.env.example` lists the
variables) or export it in your shell:

| Variable | Default | Used for |
|---|---|---|
| `POSTGRES_DB` | `spendwise` | database name |
| `POSTGRES_USER` | `spendwise` | database user |
| `POSTGRES_PASSWORD` | `spendwise-local-only` | database password; letters, digits, `-` `_` `.` only (it goes into `DATABASE_URL`) |
| `APP_PORT` | `8000` | port on 127.0.0.1 where the app is published |
| `SESSION_COOKIE_SECURE` | `false` | `true` sends the session cookie over HTTPS only; this stack is plain HTTP on localhost |
| `SESSION_TTL_DAYS` | `14` | how long a sign-in lasts |
| `AI_PROVIDER` / `AI_MODEL` / `ANTHROPIC_API_KEY` | `fake` / `claude-opus-5-5` / empty | passed to the app; see [AI providers](#ai-providers) |

Compose sets `ENVIRONMENT=production` and builds `DATABASE_URL`
(`postgresql+psycopg://USER:PASSWORD@db:5432/DB`) for the app itself. PostgreSQL applies the
credentials only when the volume is first created; after changing them, run
`docker compose down -v` (this deletes the local data) and start again.

The default password is only for this local stack: the database is not published outside the
Compose network. To connect with `psql` or a GUI, uncomment the `ports` lines under `db` in
`compose.yaml` (they bind to 127.0.0.1 only).

> ⚠️ This stack is for local use: plain HTTP, a default database password and port 8000 on
> 127.0.0.1 only. Do not deploy it as is; see [Before deploying](#before-deploying).

## Docker image without Compose

The `Dockerfile` at the repo root builds one image: Node builds the React app to static files,
and FastAPI serves them alongside the API on port 8000. Compose (above) uses this image; the
commands below run it by hand against a PostgreSQL you manage yourself.

The image needs a PostgreSQL `DATABASE_URL`. With the `spendwise-postgres` container from
[Run PostgreSQL locally](#run-postgresql-locally) on the `spendwise` network:

```bash
docker build -t spendwise .
docker run --rm --network spendwise -p 127.0.0.1:8000:8000 \
  -e DATABASE_URL="postgresql+psycopg://spendwise:$SPENDWISE_DB_PASSWORD@spendwise-postgres:5432/spendwise" \
  -e SESSION_COOKIE_SECURE=false \
  spendwise
# http://127.0.0.1:8000  (API under /api, docs at /docs)
```

- On start the container runs `alembic upgrade head`, then starts Uvicorn on `0.0.0.0:8000`
  (`backend/scripts/start.sh`).
- The image runs with `ENVIRONMENT=production`, so the session cookie is `Secure` (HTTPS only)
  unless `SESSION_COOKIE_SECURE=false` is set, as above for plain HTTP on localhost.
- The image sets `ENVIRONMENT=production` and has no `DATABASE_URL` default: without a PostgreSQL
  URL it exits at once with an error. If PostgreSQL is not reachable yet, the migration fails and
  the container exits; start the database first or add `--restart on-failure`.
- The backend serves the frontend only when `FRONTEND_DIST` is set (the image sets it). Client
  routes such as `/transactions` return `index.html`, so a refresh works; unknown `/api/...` paths
  still return JSON 404s.
- AI settings come from environment variables (`-e AI_PROVIDER=...`); no `.env` file is copied
  into the image.

> ⚠️ Not deployed yet; see [Before deploying](#before-deploying).

## Accounts and security

**Sign-in flow.** `POST /api/auth/signup` (email + password) creates an account and signs in;
`POST /api/auth/login` signs in; `POST /api/auth/logout` signs out; `GET /api/auth/me` returns
the signed-in user (`id`, `email`, `created_at`) or 401. Every other route except
`/api/health` needs a session and answers `401 {"detail": "Not authenticated"}` without one.
The frontend shows Log in and Create account pages and sends signed-out visitors there; after
signing in they return to the page they asked for.

**Passwords.** 12 to 128 characters, no other rules. Stored only as Argon2id hashes
(`argon2-cffi`, RFC 9106 low-memory parameters: 64 MiB, 3 passes, 4 lanes, random salt per
hash); hashes made with older parameters are upgraded at the next login. Passwords and hashes
never appear in API responses, logs or validation errors (`/api/auth/*` 422s omit the submitted
values). A wrong password and an unknown email get the same `401 Invalid email or password`,
and both run a full hash check so they take about as long.

**Sessions.** The session is a random 256-bit token in an `HttpOnly` cookie named
`spendwise_session` (`SameSite=Lax`, `Path=/`, host-only, `Max-Age` = `SESSION_TTL_DAYS`, default
14). JavaScript cannot read it and nothing is stored in `localStorage`. The database keeps only
the token's SHA-256, so a copy of the `sessions` table cannot be used to sign in. Logging out
deletes the session on the server, so a copied cookie stops working too. Each login issues a new
token and ends the browser's previous session. The cookie is `Secure` when
`ENVIRONMENT=production`, unless `SESSION_COOKIE_SECURE` says otherwise.

**Cross-site requests.** `SameSite=Lax` keeps the cookie off cross-site `POST`, `PUT`, `PATCH` and
`DELETE` requests, and JSON bodies are only accepted with `Content-Type: application/json`, which a
cross-site HTML form cannot send. No CORS is configured, so other origins cannot call the API
with the cookie.

**Ownership.** Every transaction and every category belongs to one user (`user_id`, required).
Each new account gets its own copy of the default categories, so renaming or deleting a default
only affects that account. Every query filters by the signed-in user in the backend; another
user's transaction or category answers exactly like one that does not exist (404, or 422
"Category N does not exist" when used in a transaction). The database also refuses a
transaction whose category belongs to someone else (composite foreign key on
`(category_id, user_id)`). Analytics only ever read the signed-in user's transactions. The owner
can never be chosen through the request: bodies with `user_id` are rejected and query
parameters or headers are ignored.

### Accounts and existing data

Data created before accounts existed has no owner, and there is no safe way to guess one, so it
is never assigned to anybody automatically. The migration that adds accounts (`0002`) checks the
database first:

- **Only the original default categories:** they are removed (every account now gets its own
  copy) and the upgrade continues.
- **Any transactions or custom categories:** the upgrade stops with an error and changes nothing.
  The app does not start until the database is reset. Back up anything you need first
  (for example `docker compose exec db pg_dump -U spendwise spendwise > backup.sql`, or copy
  `backend/spendwise.db`), then reset:

  ```bash
  docker compose down -v          # Docker Compose: deletes the local PostgreSQL volume
  rm backend/spendwise.db         # local SQLite development database
  ```

  Then sign up and re-enter the data. There is no import tool.

Downgrading below `0002` deletes all users, sessions, categories and transactions.

### Before deploying

Accounts and per-user isolation are in place, but this MVP has not been deployed. A public
deployment also needs:

- HTTPS in front of the app, with `SESSION_COOKIE_SECURE` left unset or `true`;
- a real database password (not the Compose default) and backups;
- rate limiting on `/api/auth/login` and `/api/auth/signup` at the reverse proxy: the app does
  not limit login attempts itself.

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
