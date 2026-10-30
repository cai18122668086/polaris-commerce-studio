ARG POLARIS_BASE_IMAGE
FROM ${POLARIS_BASE_IMAGE}
USER root
WORKDIR /app
ARG POLARIS_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_REVISION}
COPY backend/app /app/app
COPY backend/skill_sources /app/skill_sources
COPY backend/source_manifests /app/source_manifests
COPY backend/migrations /app/migrations
COPY backend/alembic.ini /app/alembic.ini
USER 10001:10001
