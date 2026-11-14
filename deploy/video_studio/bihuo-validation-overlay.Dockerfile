ARG POLARIS_VIDEO_BACKEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_BACKEND_BASE_IMAGE}
USER root
WORKDIR /app
# Keep the installed immutable renderers, fonts and planner request unchanged.
COPY backend/app/video_editing_apple_pipeline.py ./app/video_editing_apple_pipeline.py
COPY backend/app/bihuo_suite/planning.py ./app/bihuo_suite/planning.py
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 10001:10001
