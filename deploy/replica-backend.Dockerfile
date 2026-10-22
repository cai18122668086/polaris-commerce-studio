ARG POLARIS_REPLICA_API_BASE_IMAGE
FROM ${POLARIS_REPLICA_API_BASE_IMAGE}
USER root
WORKDIR /app
COPY backend/app /app/app
COPY backend/migrations /app/migrations
COPY backend/alembic.ini /app/alembic.ini
USER 10001:10001
