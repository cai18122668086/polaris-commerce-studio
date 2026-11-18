ARG OBSERVED_FRONTEND_IMAGE
FROM ${OBSERVED_FRONTEND_IMAGE}
USER 0:0
COPY deploy/video_studio/avatar-template-label.mjs /tmp/avatar-template-label.mjs
RUN cp -a /app/dist/client/_polaris-static /tmp/previous-avatar-label-assets \
    && node /tmp/avatar-template-label.mjs && npm run build \
    && cp -an /tmp/previous-avatar-label-assets/. /app/dist/client/_polaris-static/
USER 1000:1000
