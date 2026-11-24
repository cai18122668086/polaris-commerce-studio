import asyncio
import logging
import os
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from .celery_app import celery_app, settings
from .database import build_database
from .storage import ImageStorage, build_image_storage
from .task_runner import (
    MockTaskRunner,
    build_task_runner,
    validate_task_runner_settings,
)

validate_task_runner_settings(settings)

logger = logging.getLogger(__name__)
# Stop the job inside the event loop this long before Celery's soft limit so
# cancellation (not a signal) unwinds it and the failure path has time to run.
DEADLINE_MARGIN_SECONDS = 30


class JobDeadlineExceeded(Exception):
    pass

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
    _engine, _session_factory = build_database(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_recycle=settings.database_pool_recycle_seconds,
    )
    _storage = build_image_storage(settings)
    _runner = build_task_runner(_session_factory, settings, _storage)
    _owner_pid = process_id
    return _runner


def soft_time_limit(task: Any) -> float | None:
    """Per-message soft limit (set by the dispatcher) or the task default."""

    limits = getattr(getattr(task, "request", None), "timelimit", None) or ()
    soft = limits[1] if len(limits) > 1 else None
    return soft or getattr(task, "soft_time_limit", None)


async def _run_with_deadline(
    runner: MockTaskRunner, job_id: str, seconds: float | None
) -> Any:
    if not seconds:
        return await runner.run(job_id)
    scope = asyncio.timeout(seconds)
    try:
        async with scope:
            return await runner.run(job_id)
    except TimeoutError:
        if scope.expired():
            raise JobDeadlineExceeded(job_id) from None
        raise


def execute_job(
    runner: MockTaskRunner, job_id: str, soft_limit: float | None
) -> Any:
    deadline = (
        max(1.0, float(soft_limit) - DEADLINE_MARGIN_SECONDS) if soft_limit else None
    )
    try:
        return asyncio.run(_run_with_deadline(runner, job_id, deadline))
    except (JobDeadlineExceeded, SoftTimeLimitExceeded):
        logger.warning("job_time_limit_exceeded job_id=%s limit=%s", job_id, soft_limit)
        return runner.coordinator.fail_timed_out(job_id)


@celery_app.task(
    bind=True,
    name="polaris.process_job",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def process_job(self: Any, job_id: str) -> dict[str, str]:
    terminal_status = execute_job(
        _process_runner(), job_id, soft_time_limit(self)
    )
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
