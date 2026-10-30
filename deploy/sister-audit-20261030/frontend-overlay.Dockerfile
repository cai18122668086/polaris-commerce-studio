# Reuse only after release.py verifies the backend, dependency and build hashes.
ARG POLARIS_BASE_IMAGE
FROM ${POLARIS_BASE_IMAGE}
USER root
WORKDIR /app
ARG POLARIS_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_REVISION}
COPY app /app/app
COPY components /app/components
COPY lib /app/lib
COPY features /app/features
COPY public /app/public
RUN cp -a /app/dist/client/_polaris-static /tmp/polaris-previous-static \
    && NODE_OPTIONS=--max-old-space-size=1536 npm run build \
    && cp -an /tmp/polaris-previous-static/. /app/dist/client/_polaris-static/ \
    && rm -r /tmp/polaris-previous-static
USER 1000:1000
