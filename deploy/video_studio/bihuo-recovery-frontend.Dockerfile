ARG POLARIS_VIDEO_FRONTEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_FRONTEND_BASE_IMAGE}
USER root
WORKDIR /app
# Reuse the deployed dependencies and commerce UI; expose saved-result recovery.
COPY components/video-studio/editing-planning.tsx ./components/video-studio/editing-planning.tsx
RUN npm run typecheck && npm run build
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 1000:1000
