# BackstageIL API

Backend for BackstageIL: technical information about performance venues and halls in Israel
(stage size, rigging, power, FOH, backstage) for technicians, stage managers and production crews.

## Stack

- Python 3.13, FastAPI, SQLAlchemy 2 (async) + asyncpg, managed with [uv](https://docs.astral.sh/uv/)
- PostgreSQL on Neon
- Docker, deployed to Google Cloud Run (blue-green)

## Setup

```bash
uv sync                 # creates .venv with Python 3.13 and all dependencies
cp .env.example .env    # then fill in DATABASE_URL (your Neon dev branch)
```

## Run

```bash
uv run uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Liveness: `GET /health`
- Readiness (checks the database): `GET /health/ready`

## Docker

The same image runs locally and on Cloud Run (listens on `$PORT`, default 8080, as a non-root user).

```bash
docker compose up --build     # uses your local .env if present
curl localhost:8080/health
```

## Test and lint

```bash
uv run pytest           # the real-database test runs only when DATABASE_URL is set
uv run ruff check . && uv run ruff format --check .
uv run mypy app tests
```

## Layout

```
app/
  core/       config, logging, exceptions
  db/         engine/session, ORM base, dependencies
  routes/     HTTP endpoints (health, /api/v1/...)
  schemas/    Pydantic request/response models
  services/   business logic
tests/
```

## Configuration

All configuration comes from environment variables (see `.env.example`). Secrets are never committed:
use a local `.env` file (git-ignored) for development and the hosting platform's secret store in production.
