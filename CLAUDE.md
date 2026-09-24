# backstageil-api

FastAPI backend for BackstageIL: technical information about performance venues and halls in Israel.
Python 3.13, uv, SQLAlchemy 2 async + asyncpg, PostgreSQL on Neon, Docker on Google Cloud Run.

## Commands

```bash
uv sync                              # install (locked)
uv run uvicorn app.main:app --reload # run locally -> http://127.0.0.1:8000/docs
uv run pytest                        # tests + coverage (min 85%)
uv run pre-commit run --all-files    # gitleaks, ruff, ruff format, mypy --strict, file checks
docker compose up --build            # run the production image locally
```

## Layout and conventions

- `app/core/` config (pydantic-settings), JSON logging, exceptions
- `app/db/` engine/session (`Database`), ORM `Base`, FastAPI dependencies
- `app/routes/` one `router` per domain; versioned routers go into `api_router` (`/api/v1`)
- `app/schemas/` Pydantic request/response models
- `app/services/` business logic; raises `DomainException` subclasses, never `HTTPException`
- Errors always use the body `{"error_code", "error_type", "message", "details"}`
- Data model: **Venue → Halls** (venue = place, hall = stage with specs); data stored in English
- Every behavior change comes with tests; mypy strict must stay clean

## Way of work

1. Every change has a Jira ticket in project **BSIL**.
2. Branch `usr/uriel_s/BSIL-XXX` from an up-to-date `main`; commits and PR titles start with `BSIL-XXX:`.
3. Test before push: `uv run pytest` and `uv run pre-commit run --all-files` must pass; the PR says how it was tested.
4. `main` is protected: PR only, the `ci` check must pass, squash merge.

## Confidential info never goes into this repo

`.env`, credentials, API keys, tokens and private data (e.g. source spreadsheets with contact details)
stay on the local machine. Only `.env.example` with variable names is committed. Deployment secrets live
in GitHub Actions secrets / Cloud Run / Cloudflare. gitleaks and GitHub push protection enforce this.
