ARG POLARIS_FEEDBACK_BASE_IMAGE
FROM ${POLARIS_FEEDBACK_BASE_IMAGE}
USER root
WORKDIR /app
ENV NEXT_PUBLIC_AUTH_MODE=external \
    NEXT_PUBLIC_LOCAL_DEV_AUTH=false \
    VITE_LOCAL_DEV_AUTH=false \
    NEXT_PUBLIC_LOCAL_HELP_PREVIEW=false \
    NEXT_PUBLIC_LOCAL_HOME_PREVIEW=false \
    NEXT_PUBLIC_LOCAL_INSPIRATION_PREVIEW=false
COPY app /app/app
COPY components /app/components
COPY lib /app/lib
COPY features /app/features
RUN cp -a /app/dist/client/_polaris-static /tmp/polaris-previous-static \
    && NODE_OPTIONS=--max-old-space-size=1536 npm run build \
    && cp -an /tmp/polaris-previous-static/. /app/dist/client/_polaris-static/ \
    && rm -r /tmp/polaris-previous-static
USER 1000:1000
