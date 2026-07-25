import asyncio
from typing import Any

from sqlalchemy.exc import OperationalError

from .celery_app import celery_app, settings
from .database import build_database
from .task_runner import MockTaskRunner


@celery_app.task(
    bind=True,
    name="polaris.process_job",
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def process_job(self: Any, job_id: str) -> dict[str, str]:
    engine, session_factory = build_database(settings.database_url)
    runner = MockTaskRunner(
        session_factory,
        settings.mock_job_delay_seconds,
    )
    try:
        terminal_status = asyncio.run(runner.run(job_id))
        return {
            "job_id": job_id,
            "status": terminal_status.value if terminal_status else "not_found",
        }
    finally:
        engine.dispose()


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
    engine, session_factory = build_database(settings.database_url)
    runner = MockTaskRunner(session_factory, settings.mock_job_delay_seconds)
    try:
        terminal_status = asyncio.run(runner.cancel(job_id))
        return {
            "job_id": job_id,
            "status": terminal_status.value if terminal_status else "not_found",
        }
    finally:
        engine.dispose()
