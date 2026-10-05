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
| `SENTRY_DSN` | Sentry project DSN (see [monitoring.md](monitoring.md)) | — |
| `R2_ACCOUNT_ID` | Cloudflare account ID | same |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | R2 token for `backstageil-pictures` | R2 token for `backstageil-pictures-dev` |
| `R2_BUCKET` | `backstageil-pictures` | `backstageil-pictures-dev` |
| `PICTURES_BASE_URL` | public URL of the production bucket | public URL of the dev bucket |

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

## Picture storage (Cloudflare R2)

Hall pictures (BSIL-24) are files in R2; the API stores only their keys. Two buckets keep
dev/preview uploads out of production:

1. Cloudflare dashboard → R2 → create buckets `backstageil-pictures` and
   `backstageil-pictures-dev` (location hint: Eastern Europe / automatic, Standard storage class).
2. Each bucket → Settings → Public access: enable the `r2.dev` URL for now; after BSIL-32 connect
   a custom domain (e.g. `img.<domain>`) so files are cached by the Cloudflare CDN. Only
   `PICTURES_BASE_URL` changes: rows store keys, never full URLs.
3. R2 → Manage API tokens → create one token per bucket, permission **Object Read & Write**,
   scoped to that bucket only. Put the dev values in the local `.env` and the Vercel Preview
   environment, the production values in Vercel Production.

Files are WebP, immutable (the key contains a content hash) and stored with
`Cache-Control: public, max-age=31536000, immutable`. Uploads go through the API, so a file can be
at most 4 MB (Vercel's 4.5 MB request limit).

## Release flow (blue-green)

Merging to `main` runs CI. When CI succeeds, `.github/workflows/deploy.yml`:

1. runs `alembic upgrade head` on **PROD** (migrations must be backward-compatible: expand → migrate → contract);
2. deploys the new version with `vercel deploy --prod --skip-domain` → **live, but no traffic**;
3. smoke-tests the new deployment URL (`scripts/smoke_test.py`: health, readiness, venues, cities);
4. `scripts/promote.py` (Vercel REST API, waits until done) → **traffic switches** to the new version;
5. smoke-tests the production URL.

The workflow is skipped until the `VERCEL_PROJECT_ID` variable exists, so `main` stays green before
Vercel is set up.

If a step fails, the previous deployment keeps serving. Pushes to `main` do not deploy by themselves
(`git.deploymentEnabled.main = false` in `vercel.json`); pull requests get automatic previews.

Drill (proves nothing is promoted when a check fails): Actions → Deploy → Run workflow →
`simulate_smoke_failure = true`.

## Rollback

- Vercel dashboard → Deployments → previous production deployment → **⋯ → Promote** (instant), or
- `uv run python -m scripts.promote <previous deployment URL>` with `VERCEL_TOKEN`, `VERCEL_ORG_ID`
  and `VERCEL_PROJECT_ID` set (promote is the same traffic switch in either direction).

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
