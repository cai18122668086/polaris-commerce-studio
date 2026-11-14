ARG POLARIS_VIDEO_BACKEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_BACKEND_BASE_IMAGE}
USER root
WORKDIR /app
COPY backend/app/video_editing_bihuo_cached_render.py ./app/video_editing_bihuo_cached_render.py
COPY backend/app/bihuo_suite/planning.py ./app/bihuo_suite/planning.py
COPY backend/app/bihuo_suite/conditional_layout.py ./app/bihuo_suite/conditional_layout.py
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 10001:10001
