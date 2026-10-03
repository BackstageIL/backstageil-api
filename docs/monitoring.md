# Monitoring

| What | How | Alert |
|---|---|---|
| API up and serving data | `.github/workflows/uptime.yml` runs `scripts/smoke_test.py` against `PRODUCTION_URL` every 30 minutes (health, readiness, venues, cities; cold starts retried) | GitHub emails the failed run |
| Server errors | Sentry (free plan): unhandled exceptions and 5xx answers, e.g. the database being unreachable | Sentry emails new issues |
| Releases | `deploy.yml` smoke-tests before and after the traffic switch | GitHub emails the failed run |
| Logs | JSON logs on stdout → Vercel dashboard → Logs (kept only briefly on Hobby) | none |

Client errors (4xx) are not reported: they are answers, not incidents.

## Sentry (error tracking)

Off unless `SENTRY_DSN` is set (`app/core/monitoring.py`). What is sent:

- the exception, stack trace (no local variables), request method/path/query, environment and the
  deployed commit (`VERCEL_GIT_COMMIT_SHA`);
- never IPs, cookies, `X-API-Key` / `Authorization` headers or stack-frame variables (tested in
  `tests/test_monitoring.py`);
- no performance tracing (errors only, to stay inside the free quota).

Setup (owner, once):

1. https://sentry.io/signup/ → free **Developer** plan → create a project, platform **FastAPI**,
   named `backstageil-api`. Alerts: "Alert me on every new issue" (email).
2. Copy the project's **DSN** (Project Settings → Client Keys (DSN)).
3. Vercel → project → Settings → Environment Variables → `SENTRY_DSN` = the DSN, **Production**
   only. Redeploy (the next release does it).

Test it locally (reports to the `local` environment): run the app without a database so readiness
answers 503, then look for the new issue in Sentry:

```bash
read -s SENTRY_DSN && export SENTRY_DSN     # paste the DSN
DATABASE_URL= uv run uvicorn app.main:app   # in another terminal: curl localhost:8000/health/ready
```

## Uptime alerts by email

GitHub emails failed scheduled runs to the person who last changed the workflow's `cron` line.
Make sure GitHub → Settings → Notifications → **Actions** has email for failed workflows on.

Limits of this check:

- GitHub may start scheduled runs some minutes late, so detection takes up to ~30-40 minutes.
- GitHub disables schedules in a repository with no activity for 60 days (it emails before);
  re-enable under Actions → Uptime.
- Each check touches the database, which wakes Neon PROD for a few minutes; that's why it runs every
  30 minutes, not every minute.

Optional faster checks: a free external monitor (Better Stack or UptimeRobot, every 3-5 minutes)
on `GET /health`, which doesn't touch the database, so it costs nothing on Neon. The website gets its
own monitor once it is live (BSIL-29).
