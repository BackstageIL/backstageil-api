# backstageil-api

FastAPI backend for BackstageIL: technical information about performance venues and halls in Israel.
Python 3.14, uv, SQLAlchemy 2 async + asyncpg, PostgreSQL on Neon, deployed on Vercel (Docker kept for local runs/portability).

## Commands

```bash
uv sync                              # install (locked)
uv run uvicorn app.main:app --reload # run locally -> http://127.0.0.1:8000/docs
uv run pytest                        # tests + coverage (min 85%)
uv run pre-commit run --all-files    # gitleaks, ruff, ruff format, mypy --strict, file checks
                                     # (git add new files first: hooks only see tracked files)
docker compose up --build            # run the production image locally
uv run alembic upgrade head          # apply migrations to DATABASE_URL (Neon dev locally)
uv run alembic revision --autogenerate -m "..."  # new migration after model changes
```

## Layout and conventions

- `app/core/` config (pydantic-settings), JSON logging, exceptions
- `app/db/` engine/session (`Database`), ORM `Base`, FastAPI dependencies
- `app/routes/` one `router` per domain; versioned routers go into `api_router` (`/api/v1`)
  - public read API: `/api/v1/venues`, `/venues/{slug}`, `/venues/{slug}/halls/{slug}`,
    `/venues/{slug}/halls/{slug}/pictures`, `/venues/{slug}/recommendations`, `/cities`
    (published rows only; `public_cache` dependency sets Cache-Control on 200s)
- `app/schemas/` Pydantic request/response models
- `app/services/` business logic; raises `DomainException` subclasses, never `HTTPException`
- Errors always use the body `{"error_code", "error_type", "message", "details"}`
- Data model: **cities → venues → halls** (+ `hall_pictures`, venue `recommendations`), models in
  `app/db/models/`; data stored in English. Venue identity = city + name + street (names repeat).
- Halls read like a venue technical document: sections of typed columns (access, stage, rigging,
  masking, power, sound, lighting, backstage, rules, seating), a short factual note per column in
  `field_notes`, and `extras` ONLY for items particular to one hall (key + label). Anything most
  halls have is a column. Content is neutral facts, no opinions or tour remarks.
- Relationships are `lazy="raise"`: load related rows explicitly (`selectinload`) in services.
- Never store people's names/phones or passwords from source data.
- Picture files live in a public Vercel Blob store behind `PictureStorage`
  (`services/picture_storage.py`); uploads are re-encoded to WebP without metadata; rows store
  keys only and URLs are built from the store's base URL.
- Admin-only routes go under `app/routes/admin.py` (router-level `require_admin`); never put the
  admin key itself anywhere, only its hash in ADMIN_API_KEY_HASH.
- Admin writes commit explicitly (`get_session` never commits); bulk import runs in a savepoint
  (all-or-nothing, dry-run = rolled-back savepoint). Public queries pass `published_only=True`.
- Schema changes only via Alembic migrations (`migrations/versions/`), backward-compatible for blue-green
- Every behavior change comes with tests; mypy strict must stay clean

## Way of work

1. Every change has a Jira ticket in project **BSIL**.
2. Branch `usr/uriel_s/BSIL-XXX` from an up-to-date `main`; commits and PR titles start with `BSIL-XXX:`.
3. Test before push: `uv run pytest` and `uv run pre-commit run --all-files` must pass; the PR says how it was tested.
4. `main` is protected: PR only, the `ci` check must pass, squash merge.

## Confidential info never goes into this repo

`.env`, credentials, API keys, tokens and private data (e.g. source spreadsheets with contact details)
stay on the local machine. Only `.env.example` with variable names is committed. Deployment secrets live
in GitHub Actions secrets / Vercel / Cloudflare. gitleaks and GitHub push protection enforce this.

## Deployment

Vercel, region fra1; release = CI green on main → `.github/workflows/deploy.yml` (migrate PROD →
deploy without traffic → smoke test → promote). Runbook: `docs/deploy.md`. Production uses
`DB_POOLED=true` with Neon's pooled endpoint. Monitoring (uptime workflow, Sentry, never send credentials or frame
locals): `docs/monitoring.md`. Before AdSense goes live, revisit Vercel Hobby (non-commercial).
