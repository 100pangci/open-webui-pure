# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
ARG BUILD_HASH=dev-build
ENV APP_BUILD_HASH=${BUILD_HASH}
RUN npm run build

# Parse the changelog once, at build time. The runtime only reads the small
# JSON file, so beautifulsoup4/Markdown are not needed in the final image.
FROM python:3.11-slim-bookworm AS changelog

WORKDIR /build
COPY backend/open_webui/utils/changelog.py /build/changelog.py
COPY CHANGELOG.md /build/CHANGELOG.md
RUN python changelog.py CHANGELOG.md 5 > /build/latest-changelog.json

FROM python:3.11-slim-bookworm

# Optional feature toggles. The default image ships SQLite only and stays lean;
# turn these on (build args / compose args) only when the deployment needs them.
#
#   podman build --build-arg ENABLE_POSTGRES=true --build-arg ENABLE_REDIS=true .
ARG ENABLE_POSTGRES=false
ARG ENABLE_REDIS=false
ARG ENABLE_AZURE=false
ARG ENABLE_LDAP=false
# Extras that are rarely used in a personal deployment. Enable per feature:
#   podman build --build-arg ENABLE_PDF=true --build-arg ENABLE_CODE_FORMAT=true .
ARG ENABLE_PDF=false
ARG ENABLE_CODE_FORMAT=false
ARG ENABLE_PILLOW=false

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

COPY backend/requirements*.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip && \
    python -m pip install --no-cache-dir -r requirements-min.txt && \
    if [ "$ENABLE_POSTGRES" = "true" ]; then python -m pip install --no-cache-dir -r requirements-postgres.txt; fi && \
    if [ "$ENABLE_REDIS" = "true" ]; then python -m pip install --no-cache-dir -r requirements-redis.txt; fi && \
    if [ "$ENABLE_AZURE" = "true" ]; then python -m pip install --no-cache-dir -r requirements-azure.txt; fi && \
    if [ "$ENABLE_LDAP" = "true" ]; then python -m pip install --no-cache-dir -r requirements-ldap.txt; fi && \
    if [ "$ENABLE_PDF" = "true" ]; then python -m pip install --no-cache-dir -r requirements-pdf.txt; fi && \
    if [ "$ENABLE_CODE_FORMAT" = "true" ]; then python -m pip install --no-cache-dir -r requirements-code-format.txt; fi && \
    if [ "$ENABLE_PILLOW" = "true" ]; then python -m pip install --no-cache-dir -r requirements-pillow.txt; fi && \
    python -m pip uninstall -y pip setuptools wheel zstandard && \
    rm -rf /root/.cache /usr/local/lib/python3.11/ensurepip

COPY --from=frontend --chown=app:app /app/build /app/build
COPY --from=frontend --chown=app:app /app/package.json /app/package.json
COPY --from=frontend --chown=app:app /app/CHANGELOG.md /app/CHANGELOG.md
COPY --chown=app:app backend/ ./
COPY --from=changelog --chown=app:app /build/latest-changelog.json /app/backend/open_webui/latest-changelog.json

# Only the persistent data dir needs to be writable by the app user. Everything
# else was copied with --chown, so no recursive chown layer is needed (a
# `chown -R /app` here used to duplicate the whole tree into a new layer).
RUN mkdir -p /app/backend/data && chown app:app /app/backend/data

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --silent --fail http://localhost:${PORT}/health || exit 1

USER app
CMD ["bash", "start.sh"]
