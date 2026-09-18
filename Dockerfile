# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
ARG BUILD_HASH=dev-build
ENV APP_BUILD_HASH=${BUILD_HASH}
RUN npm run build

FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    ENV=prod \
    PORT=8080 \
    HOST=0.0.0.0 \
    OPENAI_API_BASE_URL=https://api.openai.com/v1 \
    OPENAI_API_KEY= \
    WEBUI_SECRET_KEY= \
    SCARF_NO_ANALYTICS=true \
    DO_NOT_TRACK=true \
    ANONYMIZED_TELEMETRY=false

WORKDIR /app/backend

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --gid 1000 app && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app

COPY backend/requirements.txt backend/requirements-min.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements.txt

COPY --from=frontend --chown=app:app /app/build /app/build
COPY --from=frontend --chown=app:app /app/package.json /app/package.json
COPY --from=frontend --chown=app:app /app/CHANGELOG.md /app/CHANGELOG.md
COPY --chown=app:app backend/ ./

RUN mkdir -p /app/backend/data && chown -R app:app /app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --silent --fail http://localhost:${PORT}/health || exit 1

USER app
CMD ["bash", "start.sh"]
