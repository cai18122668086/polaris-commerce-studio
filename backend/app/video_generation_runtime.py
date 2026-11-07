"""Fenced, renewable ownership shared by request and recovery workers."""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread
from types import TracebackType
from uuid import uuid4

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .auth import Principal
from .config import Settings
from .domain import UserStatus
from .errors import ApiError
from .models import UserRecord, WorkspaceMemberRecord, WorkspaceRecord, utc_now
from .video_generation_models import VideoGenerationRecord, VideoGenerationRunRecord
from .video_studio_access import require_video_studio_access

logger = logging.getLogger(__name__)


class VideoRunLost(RuntimeError):
    """The previous worker may no longer write checkpoints or start paid work."""


class VideoRunLease:
    def __init__(
        self, factory: sessionmaker[Session], job_id: str, token: str, seconds: float
    ) -> None:
        self.factory, self.job_id, self.token, self.seconds = (
            factory,
            job_id,
            token,
            seconds,
        )
        self.stopped = Event()
        self.lost = False
        self.thread: Thread | None = None

    def guard(self, session: Session) -> None:
        if self.lost:
            raise VideoRunLost("Video worker ownership ended")
        now = utc_now()
        # Always lock lease before business rows, including when ORM objects
        # already have pending edits. This also avoids heartbeat lock inversion.
        with session.no_autoflush:
            changed = session.execute(
                update(VideoGenerationRunRecord)
                .where(
                    VideoGenerationRunRecord.job_id == self.job_id,
                    VideoGenerationRunRecord.owner_token == self.token,
                    VideoGenerationRunRecord.lease_until > now,
                )
                .values(lease_until=now + timedelta(seconds=self.seconds))
            )
        if changed.rowcount != 1:  # type: ignore[attr-defined]
            self.lost = True
            raise VideoRunLost("Video worker lease was replaced or expired")

    def heartbeat(self) -> None:
        while not self.stopped.wait(self.seconds / 3):
            try:
                with self.factory() as session:
                    self.guard(session)
                    session.execute(
                        update(VideoGenerationRecord)
                        .where(
                            VideoGenerationRecord.id == self.job_id,
                            VideoGenerationRecord.status == "running",
                        )
                        .values(updated_at=utc_now())
                    )
                    session.commit()
            except VideoRunLost:
                return
            except Exception:
                # A transient DB fault does not grant a new paid submission.
                logger.warning("Video lease heartbeat unavailable for %s", self.job_id)

    def __enter__(self) -> VideoRunLease:
        self.thread = Thread(target=self.heartbeat, daemon=True, name="video-lease")
        self.thread.start()
        return self

    def abandon(self) -> None:
        self.lost = True
        self.stopped.set()

    def release(self) -> None:
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=1)
        with self.factory() as session:
            record = session.get(VideoGenerationRunRecord, self.job_id)
            if not record or record.owner_token != self.token:
                return
            delay = min(300, 15 * 2 ** min(max(0, record.attempts - 1), 5))
            session.execute(
                update(VideoGenerationRunRecord)
                .where(
                    VideoGenerationRunRecord.job_id == self.job_id,
                    VideoGenerationRunRecord.owner_token == self.token,
                )
                .values(
                    owner_token=None,
                    lease_until=None,
                    retry_at=utc_now() + timedelta(seconds=delay),
                )
            )
            session.commit()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            self.release()
        except Exception:
            logger.warning("Video lease release deferred to expiry for %s", self.job_id)


def acquire_run(
    factory: sessionmaker[Session], settings: Settings, job_id: str
) -> VideoRunLease | None:
    now, token = utc_now(), str(uuid4())
    with factory() as session:
        if not session.get(VideoGenerationRecord, job_id):
            return None
        if not session.get(VideoGenerationRunRecord, job_id):
            session.add(VideoGenerationRunRecord(job_id=job_id, attempts=0))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
        changed = session.execute(
            update(VideoGenerationRunRecord)
            .where(
                VideoGenerationRunRecord.job_id == job_id,
                or_(
                    VideoGenerationRunRecord.owner_token.is_(None),
                    VideoGenerationRunRecord.lease_until <= now,
                ),
            )
            .values(
                owner_token=token,
                lease_until=now
                + timedelta(seconds=settings.video_recovery_lease_seconds),
                attempts=VideoGenerationRunRecord.attempts + 1,
            )
        )
        session.commit()
        if changed.rowcount != 1:  # type: ignore[attr-defined]
            return None
    return VideoRunLease(factory, job_id, token, settings.video_recovery_lease_seconds)


def guard_run(session: Session) -> None:
    lease = getattr(session, "info", {}).get("video_run_lease")
    if lease:
        lease.guard(session)


def owner_can_run(session: Session, job: VideoGenerationRecord) -> bool:
    owner = session.get(UserRecord, job.owner_user_id)
    workspace = session.get(WorkspaceRecord, job.workspace_id)
    member = session.get(WorkspaceMemberRecord, (job.workspace_id, job.owner_user_id))
    if (
        not owner
        or not workspace
        or workspace.status != "active"
        or not member
        or member.status != "active"
        or member.role not in {"owner", "admin", "member"}
    ):
        return False
    try:
        require_video_studio_access(
            Principal(
                user_id=owner.id,
                email=owner.email_normalized,
                email_verified=True,
                status=UserStatus(owner.status),
            )
        )
    except (ApiError, ValueError):
        return False
    return True


def unconfirmed_paid_submission(job: VideoGenerationRecord, settings: Settings) -> bool:
    """Unknown paid receipts are never converted into permission to re-submit."""
    stages = {item.get("stage") for item in job.details.get("stage_history", [])}
    if (
        "h3_submitting" in stages
        and not job.provider_task_id
        and not job.details.get("uploaded_video_path")
    ):
        return True
    if "tts_submitting" in stages and not job.details.get("audio_url"):
        path = Path(
            job.details.get("tts_local_path")
            or settings.video_media_dir / "jobs" / job.id / "narration.mp3"
        )
        local_receipt = (
            job.details.get("tts", {}).get("provider") in {"tao", "cosyvoice"}
            and path.is_file()
            and path.stat().st_size > 0
        )
        if not local_receipt:
            return True
    routing = job.details.get("lipsync_routing") or {}
    if (
        "lipsync_submitting" in stages
        and not job.provider_task_id
        and routing.get("primary_status") not in {"failed", "skipped"}
    ):
        return True
    return bool(
        routing.get("backup_submission_started")
        and not routing.get("backup_task_id")
        and not routing.get("selected_provider")
    )
