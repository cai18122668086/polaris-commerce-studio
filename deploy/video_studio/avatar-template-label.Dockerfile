ARG OBSERVED_FRONTEND_IMAGE
FROM ${OBSERVED_FRONTEND_IMAGE}
USER 0:0
COPY deploy/video_studio/avatar-template-label.cjs /tmp/avatar-template-label.cjs
RUN cp -a /app/dist/client/_polaris-static /tmp/previous-avatar-label-assets \
    && node /tmp/avatar-template-label.cjs && npm run build \
    && cp -an /tmp/previous-avatar-label-assets/. /app/dist/client/_polaris-static/
USER 1000:1000
