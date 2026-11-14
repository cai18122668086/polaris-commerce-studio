ARG POLARIS_VIDEO_FRONTEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_FRONTEND_BASE_IMAGE}
USER root
WORKDIR /app
COPY components/video-studio/editing-template-gallery.tsx ./components/video-studio/editing-template-gallery.tsx
COPY components/video-studio/editing-flow.module.css ./components/video-studio/editing-flow.module.css
RUN npm run typecheck && npm run build
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 1000:1000
