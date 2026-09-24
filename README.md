# BackstageIL API

Backend for BackstageIL: technical information about performance venues and halls in Israel
(stage size, rigging, power, FOH, backstage) for technicians, stage managers and production crews.

## Stack

- Python 3.13, FastAPI, SQLAlchemy 2 (async) + asyncpg, managed with [uv](https://docs.astral.sh/uv/)
- PostgreSQL on Neon
- Docker, deployed to Google Cloud Run (blue-green)

## Status

Work in progress. Setup and run instructions will be added with the application scaffold.

## Configuration

All configuration comes from environment variables. Secrets are never committed:
use a local `.env` file (git-ignored) for development and the hosting platform's secret store in production.
