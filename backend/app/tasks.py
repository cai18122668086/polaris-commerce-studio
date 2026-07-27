import asyncio
import os
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .celery_app import celery_app, settings
from .database import build_database
from .storage import ImageStorage, build_image_storage
from .task_runner import MockTaskRunner

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None
_runner: MockTaskRunner | None = None
_storage: ImageStorage | None = None
_owner_pid: int | None = None


def _process_runner() -> MockTaskRunner:
    """Build one Engine/pool per Celery worker process, never per task."""

    global _engine, _session_factory, _runner, _storage, _owner_pid
    process_id = os.getpid()
    if _runner is not None and _owner_pid == process_id:
        return _runner
    if _engine is not None:
        _engine.dispose()
    _engine, _session_factory = build_database(settings.database_url)
    _storage = build_image_storage(settings)
    _runner = MockTaskRunner(
        _session_factory,
        settings.mock_job_delay_seconds,
        storage=_storage,
        xinghe_concurrency=settings.xinghe_concurrency,
        budget_limit_micros=int(settings.tengli_smoke_budget_usd * 1_000_000),
        medium_price_micros=settings.xinghe_medium_price_micros,
        high_price_micros=settings.xinghe_high_price_micros,
    )
    _owner_pid = process_id
    return _runner


@celery_app.task(
    bind=True,
    name="polaris.process_job",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def process_job(self: Any, job_id: str) -> dict[str, str]:
    del self
    terminal_status = asyncio.run(_process_runner().run(job_id))
    return {
        "job_id": job_id,
        "status": terminal_status.value if terminal_status else "not_found",
    }


@celery_app.task(
    bind=True,
    name="polaris.cancel_job",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def cancel_job_task(self: Any, job_id: str) -> dict[str, str]:
    del self
    terminal_status = asyncio.run(_process_runner().cancel(job_id))
    return {
        "job_id": job_id,
        "status": terminal_status.value if terminal_status else "not_found",
    }
