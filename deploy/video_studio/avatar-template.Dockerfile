ARG POLARIS_VIDEO_BASE_IMAGE
FROM ${POLARIS_VIDEO_BASE_IMAGE}

COPY backend/app/config.py backend/app/video_generation.py backend/app/video_providers.py backend/app/video_avatar_access.py /app/app/
COPY assets/video-studio/owned/presenter-female-v3-seated-20261118.png /assets/video-studio/owned/presenter-female-v3-seated-20261118.png

ARG SOURCE_REVISION
LABEL com.polaris.avatar_template.revision=${SOURCE_REVISION}
