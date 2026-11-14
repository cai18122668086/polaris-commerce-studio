ARG POLARIS_VIDEO_BACKEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_BACKEND_BASE_IMAGE}
USER root
WORKDIR /app
COPY --chmod=0644 backend/app/video_editing_apple_pipeline.py ./app/video_editing_apple_pipeline.py
COPY --chmod=0644 backend/app/video_editing_bihuo_cached_render.py ./app/video_editing_bihuo_cached_render.py
COPY --chmod=0644 backend/app/video_editing_planning_store.py ./app/video_editing_planning_store.py
COPY --chmod=0644 backend/app/video_editing_template_catalog.py ./app/video_editing_template_catalog.py
COPY --chmod=0644 backend/app/video_editing_unified_scenes.py ./app/video_editing_unified_scenes.py
COPY --chmod=0644 backend/app/bihuo_suite/planning.py ./app/bihuo_suite/planning.py
COPY --chmod=0644 backend/app/bihuo_suite/conditional_layout.py ./app/bihuo_suite/conditional_layout.py
COPY --chmod=0644 backend/app/bihuo_suite/video_materials.py ./app/bihuo_suite/video_materials.py
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 10001:10001
