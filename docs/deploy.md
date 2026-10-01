# Deployment runbook (Vercel)

The API runs on **Vercel (Hobby)** as a Python function in region `fra1` (Frankfurt), next to the
Neon production database. Docker stays for local runs and as a portable fallback.

> **Ads caveat:** Vercel Hobby is non-commercial and treats ads (AdSense) as commercial use.
> Before AdSense goes live (BSIL-30): upgrade to Pro, move the Docker image elsewhere, or accept
> the risk of the account being suspended.

## Environments

| | Production | Preview (each PR) | Local |
|---|---|---|---|
| URL | `PRODUCTION_URL` (repo variable) | automatic per-PR URL (Vercel-protected) | `localhost:8000` |
| Database | Neon **BackstageIL_PROD**, pooled endpoint | Neon **BackstageIL_DEV** `dev`, pooled endpoint | Neon DEV `dev`, direct |
| Admin key | production key (its own hash) | dev key hash | dev key hash |

Vercel environment variables (Project → Settings → Environment Variables):

| Variable | Production | Preview |
|---|---|---|
| `DATABASE_URL` | PROD **pooled** connection string | DEV `dev` **pooled** connection string |
| `DB_POOLED` | `true` | `true` |
| `ENVIRONMENT` | `production` | `ci` |
| `ADMIN_API_KEY_HASH` | hash of the production admin key | hash of the dev admin key |
| `CORS_ORIGINS` | the website origin(s), once it exists | — |

GitHub (`BackstageIL/backstageil-api`):

| Kind | Name | Value |
|---|---|---|
| secret | `VERCEL_TOKEN` | Vercel access token |
| secret | `VERCEL_AUTOMATION_BYPASS_SECRET` | Vercel → Settings → Deployment Protection → Protection Bypass for Automation |
| secret | `PROD_DATABASE_URL` | PROD **direct** connection string (migrations) |
| variable | `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | Vercel project settings |
| variable | `PRODUCTION_URL` | e.g. `https://<project>.vercel.app` |

Secrets are set by the owner only (`gh secret set NAME -R BackstageIL/backstageil-api`), never
committed or pasted into chats.

## Release flow (blue-green)

Merging to `main` runs CI. When CI succeeds, `.github/workflows/deploy.yml`:

1. runs `alembic upgrade head` on **PROD** (migrations must be backward-compatible: expand → migrate → contract);
2. deploys the new version with `vercel deploy --prod --skip-domain` → **live, but no traffic**;
3. smoke-tests the new deployment URL (`scripts/smoke_test.py`: health, readiness, venues, cities);
4. `vercel promote` → **traffic switches** to the new version;
5. smoke-tests the production URL.

The workflow is skipped until the `VERCEL_PROJECT_ID` variable exists, so `main` stays green before
Vercel is set up.

If a step fails, the previous deployment keeps serving. Pushes to `main` do not deploy by themselves
(`git.deploymentEnabled.main = false` in `vercel.json`); pull requests get automatic previews.

Drill (proves nothing is promoted when a check fails): Actions → Deploy → Run workflow →
`simulate_smoke_failure = true`.

## Rollback

- Vercel dashboard → Deployments → previous production deployment → **Promote** (instant), or
- `npx vercel rollback --token=…` (back to the previous production deployment).

A rollback doesn't undo migrations; that's why migrations are backward-compatible.

## Seeding production (one-off)

Run locally by the owner; the URL is read without echo, so it isn't stored in shell history:

```bash
read -s PROD_DB                    # paste the PROD *direct* connection string
DATABASE_URL="$PROD_DB" uv run alembic upgrade head
DATABASE_URL="$PROD_DB" uv run python -m scripts.seed_cities
DATABASE_URL="$PROD_DB" uv run python -m scripts.load_venues ../private/tour_venues_en.json --publish
unset PROD_DB
```
