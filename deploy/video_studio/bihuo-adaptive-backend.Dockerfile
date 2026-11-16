ARG POLARIS_VIDEO_BACKEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_BACKEND_BASE_IMAGE}
USER root
WORKDIR /app
COPY --chmod=644 backend/app/bihuo_suite/conditional_layout.py backend/app/bihuo_suite/adaptive_layout.py ./app/bihuo_suite/
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 10001:10001

