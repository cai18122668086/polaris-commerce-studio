ARG POLARIS_VIDEO_BACKEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_BACKEND_BASE_IMAGE}
USER root
WORKDIR /app
COPY backend/app/video_editing_template_catalog.py ./app/video_editing_template_catalog.py
COPY backend/app/bihuo_suite/registry.py ./app/bihuo_suite/registry.py
COPY backend/app/bihuo_suite/render.py ./app/bihuo_suite/render.py
COPY backend/app/bihuo_suite/raster_cache.py ./app/bihuo_suite/raster_cache.py
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 10001:10001
