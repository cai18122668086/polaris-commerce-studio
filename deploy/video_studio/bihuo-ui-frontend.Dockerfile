ARG POLARIS_VIDEO_FRONTEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_FRONTEND_BASE_IMAGE}
USER root
WORKDIR /app
COPY --chmod=644 components/video-studio/editing-template-gallery.tsx components/video-studio/editing-template-gallery.module.css components/video-studio/editing-project-materials.tsx components/video-studio/editing-materials.module.css components/video-studio/editing-planning.tsx components/video-studio/editing-workspace.tsx ./components/video-studio/
COPY --chmod=644 features/video-studio/template-appearance.ts features/video-studio/editing-presentation.ts ./features/video-studio/
RUN npm run typecheck && npm run build
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 1000:1000
