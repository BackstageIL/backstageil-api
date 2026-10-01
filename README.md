# BackstageIL API

Backend for BackstageIL: technical information about performance venues and halls in Israel
(stage size, rigging, power, FOH, backstage) for technicians, stage managers and production crews.

## Stack

- Python 3.14, FastAPI, SQLAlchemy 2 (async) + asyncpg, managed with [uv](https://docs.astral.sh/uv/)
- PostgreSQL on Neon
- Docker, deployed to Google Cloud Run (blue-green)

## Setup

```bash
uv sync                 # creates .venv with Python 3.14 and all dependencies
cp .env.example .env    # then fill in DATABASE_URL (your Neon dev branch)
uv run pre-commit install   # gitleaks, ruff, mypy and file checks on every commit
uv run alembic upgrade head # create/update the schema on the database in DATABASE_URL
```

## Database migrations

The schema is managed only through Alembic migrations in `migrations/versions/`
(the URL comes from `DATABASE_URL`, never from `alembic.ini`).

```bash
uv run alembic revision --autogenerate -m "add venues"   # after changing models in app/db/models/
uv run alembic upgrade head                             # apply
uv run alembic check                                    # fails if models and migrations differ
```

Migrations must stay backward-compatible for blue-green deploys (expand, migrate, then contract).

## Seed data

Cities come from the official CBS localities file (open data on data.gov.il, dataset
`localities-in-israel`): cities, local councils, kibbutzim and moshavim, upserted by official code.

```bash
uv run python -m scripts.seed_cities --dry-run        # summary only
uv run python -m scripts.seed_cities                  # write to DATABASE_URL (idempotent)
uv run python -m scripts.seed_cities --code 74        # also add one specific locality
```

Verified venue data (a local JSON file of `{venue, hall}` items, never committed) is loaded with:

```bash
uv run python -m scripts.load_venues PATH --dry-run   # validate only
uv run python -m scripts.load_venues PATH             # upsert by slug, one transaction (unpublished)
uv run python -m scripts.load_venues PATH --publish   # upsert and publish
```

Text that looks like a phone number or email is rejected: personal contact details are never stored.

## Run

```bash
uv run uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Liveness: `GET /health`
- Readiness (checks the database): `GET /health/ready`

## Public API (read-only, published data only)

| Endpoint | Returns |
|---|---|
| `GET /api/v1/venues?q=&city=&district=&type=&limit=20&offset=0` | Paged venue list (name search, filters), sorted by name |
| `GET /api/v1/venues/{venue_slug}` | Venue with its halls |
| `GET /api/v1/venues/{venue_slug}/halls/{hall_slug}` | Hall technical document (fields, `field_notes`, `extras`) |
| `GET /api/v1/cities` | Cities that have venues, with counts |

Successful responses are cacheable (`Cache-Control: public, max-age=60, s-maxage=3600, stale-while-revalidate=86400`).

## Admin access

Write endpoints require the single admin API key in the `X-API-Key` header. Only its SHA-256 hash
is configured (`ADMIN_API_KEY_HASH`); without it, admin endpoints answer 503. Repeated wrong keys
from one address get 429 for a while.

```bash
uv run python -m scripts.new_admin_key   # prints a new key (save it) and its hash (configure it)
curl -H "X-API-Key: $KEY" localhost:8000/api/v1/admin/ping   # {"status":"ok"} when the key works
```

Rotate: generate a new key, replace `ADMIN_API_KEY_HASH` (local `.env` / hosting secret), redeploy.

## Docker

The same image runs locally and on Cloud Run (listens on `$PORT`, default 8080, as a non-root user).

```bash
docker compose up --build     # uses your local .env if present
curl localhost:8080/health
```

## Test and lint

```bash
uv run pytest           # with coverage (min 85%); the real-DB test runs only when DATABASE_URL is set
uv run pre-commit run --all-files   # gitleaks, ruff, ruff format, mypy (strict), file checks
```

## Layout

```
app/
  core/       config, logging, exceptions
  db/         engine/session, ORM base, dependencies, models/ (cities, venues, halls, ...)
  routes/     HTTP endpoints (health, /api/v1/...)
  schemas/    Pydantic request/response models
  services/   business logic
tests/
```

## Configuration

All configuration comes from environment variables (see `.env.example`). Secrets are never committed:
use a local `.env` file (git-ignored) for development and the hosting platform's secret store in production.
