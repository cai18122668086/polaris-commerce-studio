FROM python:3.13.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

ARG POLARIS_INCLUDE_EDITING_PROBE=0
RUN if [ "$POLARIS_INCLUDE_EDITING_PROBE" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends ffmpeg \
      && rm -rf /var/lib/apt/lists/* \
      && mkdir -p /app/.data/editing-tasks; \
    fi

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY skill_sources ./skill_sources
COPY source_manifests ./source_manifests
COPY catalog_assets ./catalog_assets
COPY migrations ./migrations

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install .

RUN mkdir -p /app/.data/aurora-main-image \
    && groupadd --system --gid 10001 polaris \
    && useradd --system --uid 10001 --gid polaris --home-dir /app polaris \
    && chown -R polaris:polaris /app

USER polaris

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
