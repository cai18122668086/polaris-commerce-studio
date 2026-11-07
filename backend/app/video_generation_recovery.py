"""Bounded background continuation; never re-create an uncertain paid operation."""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
from typing import cast

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import utc_now
from .video_generation import RESUMABLE_STAGES, process_generation
from .video_generation_media import MODEL_REGISTRATION_STAGES
from .video_generation_models import VideoGenerationRecord, VideoGenerationRunRecord
from .video_generation_runtime import (
    VideoRunLease,
    acquire_run,
    owner_can_run,
    unconfirmed_paid_submission,
)
from .video_providers import VideoProviders

logger = logging.getLogger(__name__)
TRANSIENT_ERRORS = {
    "VIDEO_MEDIA_DOWNLOAD_FAILED",
    "VIDEO_UPLOAD_FAILED",
    "VIDEO_PROVIDER_UNAVAILABLE",
}
UNKNOWN_QUERY_STAGES = MODEL_REGISTRATION_STAGES | {
    "tts_submitting",
    "h3_submitting",
    "h3_generating",
    "lipsync_submitting",
    "lipsync_generating",
    "backup_lipsync_submitting",
    "backup_lipsync_generating",
}
CONTINUATION_STAGES = (
    RESUMABLE_STAGES
    | MODEL_REGISTRATION_STAGES
    | {
        "queued",
        "reference_ready",
        "h3_generating",
        "template_ready",
        "audio_ready",
        "audio_measured",
        "source_resolved",
        "source_measured",
        "forward_template_prepared",
        "forward_template_uploaded",
        "forward_model_ready",
        "template_duration_ready",
        "lipsync_generating",
        "provider_completed",
        "backup_lipsync_generating",
        "backup_lipsync_submitting",
        "lipsync_submitting",
        "tts_submitting",
        "h3_submitting",
    }
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def eligible(job: VideoGenerationRecord, settings: Settings) -> bool:
    if job.status not in {"queued", "running", "awaiting_resume", "unknown", "failed"}:
        return False
    if job.status == "failed" and job.error_code not in TRANSIENT_ERRORS:
        return False
    if job.stage not in CONTINUATION_STAGES or unconfirmed_paid_submission(
        job, settings
    ):
        return False
    if job.status == "unknown" and job.stage not in MODEL_REGISTRATION_STAGES:
        routing = job.details.get("lipsync_routing") or {}
        if job.stage != "tts_submitting" and not (
            job.provider_task_id
            or routing.get("backup_task_id")
            or routing.get("selected_provider")
        ):
            return False
    # Registry resumes only have enough evidence to query the original name.
    if job.stage == "forward_model_submitting":
        return bool(
            job.details.get("audio_url") and job.details.get("forward_template_url")
        )
    if job.stage == "model_submitting":
        return bool(
            job.details.get("review_approved") and job.details.get("template_url")
        )
    return True


class VideoRecoveryService:
    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        provider: VideoProviders,
    ) -> None:
        self.factory, self.settings, self.provider = factory, settings, provider
        self.pool = ThreadPoolExecutor(
            max_workers=settings.video_recovery_workers,
            thread_name_prefix="video-recovery",
        )
        self.active: dict[str, tuple[Future[None], VideoRunLease]] = {}
        self.lifecycle_lock = Lock()
        self.stopped = Event()
        self.thread: Thread | None = None

    def tick(self) -> int:
        for job_id, (future, _) in list(self.active.items()):
            if future.done():
                try:
                    future.result()
                except Exception:
                    logger.warning("Video background attempt ended for %s", job_id)
                del self.active[job_id]
        available = self.settings.video_recovery_workers - len(self.active)
        if available <= 0 or self.stopped.is_set():
            return 0
        now = utc_now()
        stale = now - timedelta(seconds=self.settings.video_recovery_lease_seconds)
        with self.factory() as session:
            ids = session.scalars(
                select(VideoGenerationRecord.id)
                .outerjoin(
                    VideoGenerationRunRecord,
                    VideoGenerationRunRecord.job_id == VideoGenerationRecord.id,
                )
                .where(
                    VideoGenerationRecord.status.in_(
                        ["queued", "running", "awaiting_resume", "unknown", "failed"]
                    ),
                    or_(
                        VideoGenerationRecord.status != "failed",
                        VideoGenerationRecord.error_code.in_(TRANSIENT_ERRORS),
                    ),
                    VideoGenerationRecord.stage.in_(CONTINUATION_STAGES),
                    or_(
                        VideoGenerationRecord.status != "unknown",
                        VideoGenerationRecord.stage.in_(UNKNOWN_QUERY_STAGES),
                    ),
                    or_(
                        VideoGenerationRecord.status != "running",
                        VideoGenerationRecord.updated_at <= stale,
                    ),
                    or_(
                        VideoGenerationRunRecord.retry_at.is_(None),
                        VideoGenerationRunRecord.retry_at <= now,
                        VideoGenerationRecord.status == "queued",
                    ),
                )
                .order_by(
                    VideoGenerationRunRecord.retry_at.asc().nullsfirst(),
                    VideoGenerationRecord.created_at,
                )
                .limit(100)
            ).all()
        started = 0
        for job_id in ids:
            if job_id in self.active or self.stopped.is_set():
                continue
            lease = acquire_run(self.factory, self.settings, job_id)
            if lease is None:
                continue
            try:
                with self.factory() as session:
                    job = session.get(VideoGenerationRecord, job_id)
                    if not job:
                        lease.release()
                        continue
                    lease.guard(session)
                    if not owner_can_run(session, job):
                        session.rollback()
                        lease.release()
                        continue
                    if job.status == "running" and utc(job.updated_at) > stale:
                        session.rollback()
                        lease.release()
                        continue
                    if not eligible(job, self.settings):
                        # An interrupted unconfirmed paid submission is retained,
                        # never put back through the submitting branch.
                        if job.status in {
                            "queued",
                            "running",
                        } and unconfirmed_paid_submission(job, self.settings):
                            job.status, job.error_code = (
                                "unknown",
                                "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                            )
                        session.commit()
                        lease.release()
                        continue
                    changed = session.execute(
                        update(VideoGenerationRecord)
                        .where(
                            VideoGenerationRecord.id == job_id,
                            VideoGenerationRecord.status == job.status,
                        )
                        .values(status="queued")
                    )
                    session.commit()
                    if cast(CursorResult, changed).rowcount != 1:
                        lease.release()
                        continue
                with self.lifecycle_lock:
                    if (
                        self.stopped.is_set()
                        or len(self.active) >= self.settings.video_recovery_workers
                    ):
                        lease.release()
                        continue
                    future = self.pool.submit(
                        process_generation,
                        self.factory,
                        self.settings,
                        job_id,
                        self.provider,
                        lease=lease,
                    )
                    self.active[job_id] = (future, lease)
                started += 1
                if started >= available:
                    break
            except Exception:
                lease.release()
                raise
        return started

    def run(self) -> None:
        while not self.stopped.is_set():
            try:
                self.tick()
            except Exception:
                logger.warning("Video recovery scan deferred after a database error")
            self.stopped.wait(self.settings.video_recovery_interval_seconds)

    def start(self) -> None:
        self.thread = Thread(target=self.run, daemon=True, name="video-recovery-scan")
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)
        with self.lifecycle_lock:
            for future, lease in list(self.active.values()):
                lease.abandon()
                if future.cancel():
                    lease.release()
            self.pool.shutdown(wait=False, cancel_futures=True)
