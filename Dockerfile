# syntax=docker/dockerfile:1

# ---- Build stage: install locked dependencies into a virtualenv with uv ----
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# Dependencies first (cached layer), app code is not needed for this step
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ---- Runtime stage: slim image, non-root user, no build tools ----
FROM python:3.14-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

RUN useradd --system --uid 10001 --no-create-home app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /srv
COPY app ./app

USER app

EXPOSE 8080

# Cloud Run sets PORT; default to 8080 locally
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
