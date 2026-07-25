import asyncio
import socket
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .domain import OutboxStatus
from .models import OutboxEventRecord, utc_now
from .task_runner import MockTaskRunner


def publish_pending_events(
    settings: Settings,
    session_factory: sessionmaker[Session],
    task_runner: MockTaskRunner,
    *,
    limit: int = 20,
) -> int:
    worker_id = f"outbox-{socket.gethostname()}"
    now = utc_now()
    stale_lock_before = now - timedelta(minutes=5)
    with session_factory() as session:
        events = session.scalars(
            select(OutboxEventRecord)
            .where(
                or_(
                    and_(
                        OutboxEventRecord.status.in_(
                            [
                                OutboxStatus.PENDING.value,
                                OutboxStatus.FAILED.value,
                            ]
                        ),
                        OutboxEventRecord.available_at <= now,
                    ),
                    and_(
                        OutboxEventRecord.status == OutboxStatus.PUBLISHING.value,
                        OutboxEventRecord.locked_at.is_not(None),
                        OutboxEventRecord.locked_at < stale_lock_before,
                    ),
                ),
            )
            .order_by(OutboxEventRecord.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        event_ids = [event.id for event in events]
        for event in events:
            event.status = OutboxStatus.PUBLISHING.value
            event.locked_at = utc_now()
            event.locked_by = worker_id
            event.attempt_count += 1
        session.commit()

    published = 0
    for event_id in event_ids:
        try:
            with session_factory() as session:
                current_event = session.get(OutboxEventRecord, event_id)
                if current_event is None:
                    continue
                event_type = current_event.event_type
                dedupe_key = current_event.dedupe_key
                payload = dict(current_event.payload)
            _dispatch(
                settings,
                task_runner,
                event_type=event_type,
                dedupe_key=dedupe_key,
                payload=payload,
            )
            with session_factory() as session:
                current_event = session.get(OutboxEventRecord, event_id)
                if current_event is None:
                    continue
                current_event.status = OutboxStatus.PUBLISHED.value
                current_event.published_at = utc_now()
                current_event.last_error = None
                session.commit()
                published += 1
        except Exception as exc:
            with session_factory() as session:
                failed_event = session.get(OutboxEventRecord, event_id)
                if failed_event is None:
                    continue
                failed_event.status = OutboxStatus.FAILED.value
                failed_event.available_at = utc_now() + timedelta(
                    seconds=min(60, 2 ** min(failed_event.attempt_count, 5))
                )
                failed_event.last_error = _safe_error(exc)
                session.commit()
    return published


def _dispatch(
    settings: Settings,
    task_runner: MockTaskRunner,
    *,
    event_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
) -> None:
    job_id = str(payload["job_id"])
    if settings.task_dispatcher == "inline":
        if event_type == "job.cancel_requested":
            asyncio.run(task_runner.cancel(job_id))
        else:
            asyncio.run(task_runner.run(job_id))
        return

    from .tasks import cancel_job_task, process_job

    task: Any = cancel_job_task if event_type == "job.cancel_requested" else process_job
    task.apply_async(args=[job_id], task_id=dedupe_key)


def _safe_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:500]}"
