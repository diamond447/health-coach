# syntax=docker/dockerfile:1
FROM node:24-alpine AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.15-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Dependencies only, so this layer (~130 MB) changes with uv.lock and not with every
# release. rich and its renderers are only used by typer's coloured help (turned off
# below with TYPER_USE_RICH=0) and would make the MCP SDK log through RichHandler.
RUN uv sync --frozen --no-dev --no-install-project \
    --no-install-package rich --no-install-package pygments \
    --no-install-package markdown-it-py --no-install-package mdurl
COPY src ./src
COPY --from=web-build /app/src/health_coach/web/static ./src/health_coach/web/static
RUN /app/.venv/bin/python -m compileall -q --invalidation-mode unchecked-hash src

FROM python:3.15-slim-bookworm
RUN useradd --system --uid 10001 --home /app app \
    && printf '#!/bin/sh\nexec python -m health_coach "$@"\n' > /usr/local/bin/health-coach \
    && chmod 755 /usr/local/bin/health-coach
WORKDIR /app
COPY --from=build --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app LICENSE /app/
COPY --from=build --chown=app:app /app/src /app/src
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH=/app/src PYTHONUNBUFFERED=1 TYPER_USE_RICH=0
USER app
ENTRYPOINT ["health-coach"]
CMD ["--help"]
