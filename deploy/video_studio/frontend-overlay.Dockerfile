ARG POLARIS_VIDEO_FRONTEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_FRONTEND_BASE_IMAGE}
USER root
WORKDIR /app
# Retain the currently deployed commerce UI and patch only the reviewed video UI.
COPY app/video-studio ./app/video-studio
COPY components/video-studio ./components/video-studio
COPY features/video-studio ./features/video-studio
COPY lib/api/generated/openapi.d.ts ./lib/api/generated/openapi.d.ts
RUN npm run typecheck && npm run build
USER 1000:1000
