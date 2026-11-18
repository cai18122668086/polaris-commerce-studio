ARG OBSERVED_FRONTEND_IMAGE
FROM ${OBSERVED_FRONTEND_IMAGE}
USER 0:0
COPY deploy/video_studio/avatar-template-label.cjs /tmp/avatar-template-label.cjs
RUN node /tmp/avatar-template-label.cjs && npm run build
USER 1000:1000
