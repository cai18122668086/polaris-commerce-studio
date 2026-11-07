"""Cost-first failover: a slow or unknown task never starts another video.

Only a confirmed primary failure/rejection can switch an existing job. Two
recent confirmed failures route NEW jobs directly to the backup for a cooldown.
Every paid submission has a committed intent and is never blindly retried.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .errors import ApiError
from .models import utc_now
from .video_generation_media import set_stage
from .video_generation_models import VideoGenerationRecord, VideoLipsyncAvatarRecord
from .video_generation_runtime import guard_run
from .video_providers import VideoProviders, safe_media_url
from .video_stage_timing import transition

SUCCESS = {"completed", "success", "succeeded"}
# Cancellation does not prove the remote computation stopped. Do not switch.
FAILURE = {"failed", "error"}


def stamp() -> str:
    return utc_now().isoformat()


def route(job: VideoGenerationRecord) -> dict[str, Any]:
    return dict(job.details.get("lipsync_routing") or {})


def checkpoint(session: Session, job: VideoGenerationRecord, **changes: Any) -> None:
    guard_run(session)
    job.details = {**job.details, "lipsync_routing": {**route(job), **changes}}
    job.updated_at = utc_now()
    session.commit()


def backup_available(settings: Settings, job: VideoGenerationRecord) -> bool:
    return bool(
        settings.video_lipsync_failover_enabled
        and settings.skyhuman_api_key.get_secret_value()
        and (
            settings.video_skyhuman_auto_register
            or settings.video_skyhuman_avatar_map.get(str(job.details["model_id"]))
        )
    )


def breaker_open(
    session: Session, job: VideoGenerationRecord, settings: Settings
) -> bool:
    """Use durable receipts scoped to the same owner/workspace; no process globals."""
    if not settings.video_lipsync_breaker_seconds:
        return False
    since = utc_now() - timedelta(seconds=settings.video_lipsync_breaker_seconds)
    rows = session.scalars(
        select(VideoGenerationRecord)
        .where(
            VideoGenerationRecord.workspace_id == job.workspace_id,
            VideoGenerationRecord.owner_user_id == job.owner_user_id,
            VideoGenerationRecord.kind == "lipsync",
            VideoGenerationRecord.id != job.id,
            VideoGenerationRecord.updated_at >= since,
        )
        .order_by(VideoGenerationRecord.updated_at.desc())
        .limit(20)
    ).all()
    failures = 0
    for previous in rows:
        primary = route(previous).get("primary_status")
        finished = route(previous).get("primary_finished_at")
        if finished and datetime.fromisoformat(finished) < since:
            continue
        if primary in SUCCESS:
            return failures >= 2
        if primary in FAILURE or (
            not primary and previous.error_code == "VIDEO_PROVIDER_TASK_FAILED"
        ):
            failures += 1
            if failures >= 2:
                return True
    return False


def started_at(job: VideoGenerationRecord) -> str:
    for item in job.details.get("stage_history", []):
        if item.get("stage") == "lipsync_generating":
            return str(item["started_at"])
    return stamp()


def long_wait(job: VideoGenerationRecord, seconds: float) -> bool:
    value = route(job).get("primary_started_at")
    if not value:
        return False
    start = datetime.fromisoformat(value)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    return (utc_now() - start).total_seconds() >= seconds


def query(provider: VideoProviders, vendor: str, path: str) -> dict[str, Any]:
    # A slow status GET must not turn 180 polls into half an hour of waiting.
    data = provider.request(vendor, "GET", path, timeout=httpx.Timeout(15, connect=5))
    if vendor == "skyhuman":
        return {**(data.get("data") or {}), **data}
    return data


def avatar_for_backup(
    session: Session,
    job: VideoGenerationRecord,
    settings: Settings,
    provider: VideoProviders,
) -> str | None:
    model_id = str(job.details["model_id"])
    mapped = settings.video_skyhuman_avatar_map.get(model_id)
    if mapped:
        return mapped
    if not settings.video_skyhuman_auto_register:
        raise ApiError(409, "VIDEO_BACKUP_AVATAR_MISSING", "备用渠道尚未准备当前形象。")
    conditions = (
        VideoLipsyncAvatarRecord.workspace_id == job.workspace_id,
        VideoLipsyncAvatarRecord.owner_user_id == job.owner_user_id,
        VideoLipsyncAvatarRecord.model_id == model_id,
    )
    asset = session.scalar(select(VideoLipsyncAvatarRecord).where(*conditions))
    if asset is None:
        source = job.details.get("forward_template_url") or (
            job.details.get("source_video") or {}
        ).get("video_url")
        if not source:
            raise ApiError(
                409, "VIDEO_BACKUP_AVATAR_MISSING", "备用渠道缺少原动作素材。"
            )
        source = safe_media_url(source)
        asset = VideoLipsyncAvatarRecord(
            id=str(uuid4()),
            workspace_id=job.workspace_id,
            owner_user_id=job.owner_user_id,
            model_id=model_id,
            status="submitting",
        )
        session.add(asset)
        try:
            session.commit()  # Unique reservation BEFORE the billable clone POST.
        except IntegrityError:
            session.rollback()
            asset = session.scalar(select(VideoLipsyncAvatarRecord).where(*conditions))
            assert asset is not None
        else:
            try:
                data = provider.request(
                    "skyhuman",
                    "POST",
                    "/api/v2/fly/avatar/create_by_video",
                    headers={"Idempotency-Key": "polaris-avatar-" + asset.id},
                    json={
                        "title": "极光备用-" + asset.id,
                        "video_url": source,
                        "human_type": "v2",
                    },
                )
                asset.provider_task_id = data.get("task_id") or None
                asset.avatar_code = data.get("avatar_code") or None
                if not asset.provider_task_id and not asset.avatar_code:
                    raise ApiError(
                        502,
                        "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                        "备用形象登记结果待确认。",
                    )
                asset.status = "ready" if asset.avatar_code else "processing"
                session.commit()
            except ApiError as error:
                asset.status = (
                    "failed" if error.code == "VIDEO_PROVIDER_REJECTED" else "unknown"
                )
                asset.error_code = error.code
                session.commit()
                raise
    if asset.status == "ready" and asset.avatar_code:
        return asset.avatar_code
    if asset.status == "failed":
        raise ApiError(
            502, asset.error_code or "VIDEO_BACKUP_AVATAR_FAILED", "备用形象准备失败。"
        )
    if not asset.provider_task_id:
        updated = asset.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        if asset.status == "submitting" and (utc_now() - updated).total_seconds() < 180:
            return None
        # Another worker owns this reservation or its POST outcome was lost.
        # Never register the same asset twice, including after a restart.
        raise ApiError(
            502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "备用形象登记结果待确认。"
        )
    data = query(
        provider,
        "skyhuman",
        "/api/v2/fly/avatar/task?task_id=" + asset.provider_task_id,
    )
    if str(data.get("status")) == "4":
        asset.status, asset.error_code = "failed", "VIDEO_BACKUP_AVATAR_FAILED"
        session.commit()
        raise ApiError(502, "VIDEO_BACKUP_AVATAR_FAILED", "备用形象准备失败。")
    if str(data.get("status")) == "3" and data.get("avatar"):
        asset.status, asset.avatar_code = "ready", data["avatar"]
        session.commit()
        return asset.avatar_code
    return None


def wait_for_resume(session: Session, job: VideoGenerationRecord) -> bool:
    guard_run(session)
    job.status = "awaiting_resume"
    job.details = {
        **job.details,
        "stage_history": transition(
            job.details.get("stage_history"),
            job.stage,
            finish=True,
            outcome="awaiting_resume",
        ),
    }
    session.commit()
    return False


def run_lipsync(
    session: Session,
    job: VideoGenerationRecord,
    settings: Settings,
    provider: VideoProviders,
) -> bool:
    fallback = backup_available(settings, job)
    state = route(job)
    if state.get("selected_provider"):
        return True  # Download recovery reuses the recorded winning result.
    if not job.provider_task_id and not state:
        if fallback and breaker_open(session, job, settings):
            checkpoint(
                session, job, primary_status="skipped", switch_reason="recent_failures"
            )
        else:
            checkpoint(
                session, job, primary_status="submitting", primary_started_at=stamp()
            )
            set_stage(session, job, "lipsync_submitting")
            try:
                data = provider.request(
                    "quanyu",
                    "POST",
                    "/api/digital_human/submit",
                    json={
                        "model_id": job.details["model_id"],
                        "audio_url": job.details["audio_url"],
                    },
                )
                if not data.get("task_id"):
                    raise ApiError(
                        502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "任务结果未确认。"
                    )
                job.provider_task_id = data["task_id"]
                checkpoint(session, job, primary_status="processing")
                set_stage(
                    session,
                    job,
                    "lipsync_generating",
                    billing=job.details.get("billing", []) + [data.get("billing", {})],
                )
            except ApiError as error:
                if not fallback or error.code != "VIDEO_PROVIDER_REJECTED":
                    raise
                checkpoint(
                    session,
                    job,
                    primary_status="failed",
                    primary_finished_at=stamp(),
                    switch_reason="primary_rejected",
                )
    elif job.provider_task_id and not state:
        # Jobs submitted before this release retain their original task ID/time.
        checkpoint(
            session,
            job,
            primary_status="processing",
            primary_started_at=started_at(job),
        )

    deadline = time.monotonic() + settings.video_lipsync_poll_window_seconds
    while time.monotonic() < deadline:
        state = route(job)
        if state.get("primary_status") not in FAILURE | {"skipped"}:
            if not job.provider_task_id:
                raise ApiError(
                    502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "原渠道提交结果待确认。"
                )
            try:
                data = query(provider, "quanyu", "/api/status/" + job.provider_task_id)
            except ApiError:
                checkpoint(
                    session,
                    job,
                    long_wait=long_wait(job, settings.video_lipsync_long_wait_seconds),
                )
                time.sleep(5)
                continue  # Unavailable GET does not prove failure; no backup.
            status = str(data.get("status", "")).lower()
            checkpoint(
                session,
                job,
                primary_status=status or "processing",
                primary_progress=data.get("progress"),
                long_wait=long_wait(job, settings.video_lipsync_long_wait_seconds),
            )
            if status in SUCCESS:
                checkpoint(
                    session,
                    job,
                    selected_provider="quanyu",
                    primary_finished_at=stamp(),
                )
                set_stage(
                    session,
                    job,
                    "provider_completed",
                    provider_result=data.get("result", {}),
                )
                return True
            if status not in FAILURE:
                time.sleep(5)
                continue  # Even after ten minutes, preserve this sole paid task.
            if fallback:
                checkpoint(
                    session,
                    job,
                    switch_reason="primary_failed",
                    primary_finished_at=stamp(),
                )

        if not fallback:
            raise ApiError(502, "VIDEO_PROVIDER_TASK_FAILED", "供应商任务失败。")
        state = route(job)
        backup_task = state.get("backup_task_id")
        if not backup_task:
            if state.get("backup_submission_started"):
                raise ApiError(
                    502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "备用提交结果待确认。"
                )
            set_stage(session, job, "backup_avatar_preparing")
            try:
                avatar = avatar_for_backup(session, job, settings, provider)
            except ApiError as error:
                if error.code == "VIDEO_PROVIDER_UNAVAILABLE":
                    time.sleep(5)
                    continue
                raise
            if avatar is None:
                time.sleep(5)
                continue
            checkpoint(
                session, job, backup_submission_started=True, backup_started_at=stamp()
            )
            set_stage(session, job, "backup_lipsync_submitting")
            data = provider.request(
                "skyhuman",
                "POST",
                "/api/v2/fly/video/create_by_audio",
                json={
                    "audio_url": job.details["audio_url"],
                    "avatar": avatar,
                    "title": "极光口播-" + job.id,
                },
            )
            backup_task = data.get("task_id")
            if not backup_task:
                raise ApiError(
                    502, "VIDEO_PROVIDER_OUTCOME_UNKNOWN", "备用提交结果待确认。"
                )
            checkpoint(
                session, job, backup_task_id=backup_task, backup_status="processing"
            )
            set_stage(session, job, "backup_lipsync_generating")
        try:
            data = query(
                provider, "skyhuman", "/api/v2/fly/video/task?task_id=" + backup_task
            )
        except ApiError:
            checkpoint(session, job)
            time.sleep(5)
            continue
        status = str(data.get("status", ""))
        checkpoint(session, job, backup_status=status)
        if status == "3":
            url = safe_media_url(data.get("video_url") or data.get("video_Url") or "")
            checkpoint(session, job, selected_provider="skyhuman", result_url=url)
            set_stage(session, job, "provider_completed")
            return True
        if status == "4":
            raise ApiError(502, "VIDEO_PROVIDER_TASK_FAILED", "备用渠道任务失败。")
        time.sleep(5)
    return wait_for_resume(session, job)
