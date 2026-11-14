ARG POLARIS_VIDEO_FRONTEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_FRONTEND_BASE_IMAGE} AS build
USER root
WORKDIR /app
COPY --chmod=0644 components/video-studio/editing-planning.tsx ./components/video-studio/editing-planning.tsx
COPY --chmod=0644 components/video-studio/editing-project-materials.tsx ./components/video-studio/editing-project-materials.tsx
COPY --chmod=0644 components/video-studio/editing-template-gallery.tsx ./components/video-studio/editing-template-gallery.tsx
RUN npm run build
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 1000:1000
