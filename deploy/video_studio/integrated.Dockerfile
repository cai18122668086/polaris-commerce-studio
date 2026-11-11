ARG POLARIS_EDITING_PYTHON_IMAGE
FROM ${POLARIS_EDITING_PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.editing-api.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r /tmp/requirements.lock
COPY backend/pyproject.toml backend/README.md backend/editing-constraints.txt ./
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/third_party ./third_party
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/catalog_assets ./catalog_assets
COPY backend/skill_sources ./skill_sources
COPY backend/source_manifests ./source_manifests
COPY assets/video-studio/owned /assets/video-studio/owned
RUN python -m pip install --no-cache-dir torch==2.5.1+cpu torchaudio==2.5.1+cpu --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -c editing-constraints.txt '.[editing,editing-zh]' \
    && python -m playwright install --with-deps chromium \
    && python -m pip check \
    && rm -rf /root/.cache /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 polaris \
    && useradd --system --uid 10001 --gid polaris --home-dir /app polaris \
    && mkdir -p /app/.data/editing-tasks /app/.data/video-studio \
    && chown -R polaris:polaris /app/.data /ms-playwright
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
