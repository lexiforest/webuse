FROM node:22-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV WEBUSE_WORKER_COMMAND=/app/.venv/bin/webuse

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock README.md /app/
COPY src /app/src
RUN uv sync --frozen

COPY ui/package.json ui/package-lock.json /app/ui/
WORKDIR /app/ui
RUN npm ci

COPY ui /app/ui
RUN npm run build

EXPOSE 3000 8787
