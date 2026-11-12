ARG POLARIS_VIDEO_BACKEND_BASE_IMAGE
FROM ${POLARIS_VIDEO_BACKEND_BASE_IMAGE}
USER root
WORKDIR /app
RUN python -m pip install --no-cache-dir --no-deps pypinyin==0.55.0 && python -m pip check
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/pyproject.toml backend/editing-constraints.txt ./
ARG POLARIS_RELEASE_REVISION
LABEL org.opencontainers.image.revision=${POLARIS_RELEASE_REVISION}
USER 10001:10001
