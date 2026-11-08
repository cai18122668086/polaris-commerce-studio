"""Separate editing queue with durable DB claims, cancellation and stale-run fences."""

import hashlib
import importlib.metadata
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from .celery_app import celery_app
from .config import Settings
from .database import build_database
from .motion_library import (
    MOTION_SHA256,
    atomic_json,
    read_json,
    sha256,
    verify_package,
)
from .video_editing_contracts import Transcript
from .video_editing_pipeline import (
    EditingFailure,
    compile_baseline,
    native_export,
    prepare,
    run,
    validate_result,
)
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingAttemptRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_studio_models import VideoScriptVersionRecord


def eligible() -> ColumnElement[bool]:
    return or_(
        EditingTaskRecord.status == "queued",
        (EditingTaskRecord.status == "running")
        & (EditingTaskRecord.lease_until < datetime.now(UTC)),
    )


def asr_profile(settings: Settings, language: str, reference: str | None) -> str | None:
    """Do not reuse clocks after model/config/language/reference changes."""
    model_path = Path(settings.video_editing_asr_model)
    provider = settings.video_editing_asr_provider
    identity: str | dict[str, str]
    if provider == "funasr":
        from .video_editing_funasr import PROCESSING_VERSION, bundle_identity

        identity = bundle_identity(model_path)
        processing = PROCESSING_VERSION
    elif model_path.is_dir() and (model_path / "model.bin").is_file():
        identity = {
            p.name: sha256(p)
            for p in sorted(model_path.iterdir())
            if p.is_file() and p.suffix in {".bin", ".json", ".txt"}
        }
        processing = "word-clock/1"
    else:
        # Unpinned downloadable aliases may run, but are never a reusable cache.
        return None
    payload = {
        "provider": provider,
        "version": importlib.metadata.version(provider),
        "processing": processing,
        "identity": identity,
        "device": settings.video_editing_asr_device,
        "language": language,
        "reference": reference,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def process(task_id: str, settings: Settings, factory: sessionmaker[Session]) -> None:
    token = str(uuid4())
    now = datetime.now(UTC)
    with factory() as session:
        claimed = session.execute(
            update(EditingTaskRecord)
            .where(EditingTaskRecord.id == task_id, eligible())
            .values(
                owner_token=token,
                status="running",
                stage="preparing",
                attempts=EditingTaskRecord.attempts + 1,
                revision=EditingTaskRecord.revision + 1,
                lease_until=now
                + timedelta(seconds=settings.video_editing_lease_seconds),
            )
        )
        if not cast(CursorResult, claimed).rowcount:
            session.rollback()
            return
        row = session.get(EditingTaskRecord, task_id)
        assert row is not None
        attempt = EditingAttemptRecord(
            id=token,
            task_id=task_id,
            number=row.attempts,
            status="running",
            started_at=now,
        )
        session.add(attempt)
        # A reclaimed attempt cannot later publish artifacts.
        session.execute(
            update(EditingAttemptRecord)
            .where(
                EditingAttemptRecord.task_id == task_id,
                EditingAttemptRecord.id != token,
                EditingAttemptRecord.status == "running",
            )
            .values(
                status="superseded", finished_at=now, error_code="EDITING_LEASE_EXPIRED"
            )
        )
        session.commit()
        source = session.get(EditingSourceRecord, row.source_id)
        assert source is not None
        snapshot: dict[str, Any] = {
            "source_path": source.media_path,
            "source_sha256": source.media_sha256,
            "options": row.options,
            "checkpoint": row.checkpoint,
            "library_release": row.library_release,
            "confirmed_version_id": source.confirmed_version_id,
        }
        version = (
            session.get(VideoScriptVersionRecord, source.confirmed_version_id)
            if source.confirmed_version_id
            else None
        )
        snapshot["reference"] = (
            version.snapshot.get("draft", {}).get("text") if version else None
        )
    root = (settings.video_editing_tasks_dir / task_id / token[:8]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    last_heartbeat = [datetime.min.replace(tzinfo=UTC)]

    def guard(force: bool = False) -> None:
        moment = datetime.now(UTC)
        if not force and (moment - last_heartbeat[0]).total_seconds() < 2:
            return
        with factory() as session:
            saved = session.get(EditingTaskRecord, task_id)
            if not saved or saved.owner_token != token or saved.status != "running":
                raise EditingFailure("EDITING_LEASE_LOST")
            if saved.cancel_requested:
                raise EditingFailure("EDITING_CANCELLED")
            renewed = session.execute(
                update(EditingTaskRecord)
                .execution_options(synchronize_session=False)
                .where(
                    EditingTaskRecord.id == task_id,
                    EditingTaskRecord.owner_token == token,
                    EditingTaskRecord.status == "running",
                    EditingTaskRecord.lease_until >= moment,
                    EditingTaskRecord.cancel_requested.is_(False),
                )
                .values(
                    lease_until=moment
                    + timedelta(seconds=settings.video_editing_lease_seconds)
                )
            )
            if not cast(CursorResult, renewed).rowcount:
                raise EditingFailure("EDITING_LEASE_LOST")
            session.commit()
        last_heartbeat[0] = moment

    def stage(name: str, **checkpoint: Any) -> None:
        guard(True)
        with factory() as session:
            saved = session.get(EditingTaskRecord, task_id)
            assert saved is not None
            merged = {**saved.checkpoint, **checkpoint}
            result = session.execute(
                update(EditingTaskRecord)
                .where(
                    EditingTaskRecord.id == task_id,
                    EditingTaskRecord.owner_token == token,
                    EditingTaskRecord.status == "running",
                    EditingTaskRecord.cancel_requested.is_(False),
                )
                .values(
                    stage=name,
                    checkpoint=merged,
                    revision=EditingTaskRecord.revision + 1,
                )
            )
            if not cast(CursorResult, result).rowcount:
                raise EditingFailure("EDITING_LEASE_LOST")
            session.commit()

    try:
        guard(True)
        if not settings.video_editing_enabled:
            raise EditingFailure("EDITING_DISABLED")
        if snapshot["options"].get("source_subtitles") == "unknown":
            raise EditingFailure("EDITING_SOURCE_SUBTITLES_REVIEW_REQUIRED")
        if snapshot["library_release"] != MOTION_SHA256:
            raise EditingFailure("EDITING_LIBRARY_CHANGED")
        verify_package(settings.video_editing_library_dir)
        prepared = prepare(
            Path(snapshot["source_path"]),
            snapshot["source_sha256"],
            root,
            settings,
            guard,
        )
        stage("transcribing")
        profile = asr_profile(
            settings, snapshot["options"]["language"], snapshot["reference"]
        )
        cached = snapshot["checkpoint"].get("transcript")
        transcript = None
        if (
            cached
            and profile is not None
            and cached.get("profile") == profile
            and Path(cached["path"]).is_file()
            and sha256(Path(cached["path"])) == cached["sha256"]
        ):
            candidate = Transcript.model_validate(read_json(Path(cached["path"])))
            if (
                candidate.source_sha256 == prepared["source_sha256"]
                and candidate.audio_sha256 == prepared["audio_sha256"]
                and candidate.model == settings.video_editing_asr_model
                and candidate.provider == settings.video_editing_asr_provider
            ):
                transcript = candidate
        if transcript is None:
            atomic_json(
                root / "asr-config.json",
                {
                    "provider": settings.video_editing_asr_provider,
                    "model": settings.video_editing_asr_model,
                    "device": settings.video_editing_asr_device,
                    "reference": snapshot["reference"],
                    "language": snapshot["options"]["language"],
                },
            )
            run(
                [
                    settings.video_editing_python,
                    "-B",
                    "-X",
                    "utf8",
                    "-m",
                    "app.video_editing_asr",
                    "--instance",
                    str(root),
                ],
                root,
                settings,
                guard,
                "asr",
            )
            transcript = Transcript.model_validate(read_json(root / "transcript.json"))
        else:
            atomic_json(root / "transcript.json", transcript.model_dump(mode="json"))
        stage(
            "compiling",
            transcript={
                "path": str(root / "transcript.json"),
                "sha256": sha256(root / "transcript.json"),
                "profile": profile,
            },
        )
        compile_baseline(root, prepared, transcript, snapshot["options"], settings)
        stage("rendering", render_plan_sha256=sha256(root / "episode.json"))
        final = native_export(root, settings, guard)
        stage("validating")
        validation = validate_result(final, prepared, root, settings, guard)
        stage("storing")
        artifacts = [
            ("final", final, "video/mp4"),
            ("transcript", root / "transcript.json", "application/json"),
            ("caption_anchors", root / "caption-anchors.json", "application/json"),
            ("receipt", root / "validation.json", "application/json"),
        ]
        guard(True)
        with factory() as session:
            fenced = session.execute(
                update(EditingTaskRecord)
                .where(
                    EditingTaskRecord.id == task_id,
                    EditingTaskRecord.owner_token == token,
                    EditingTaskRecord.status == "running",
                    EditingTaskRecord.lease_until >= datetime.now(UTC),
                    EditingTaskRecord.cancel_requested.is_(False),
                )
                .values(
                    status="completed",
                    stage="completed",
                    owner_token=None,
                    lease_until=None,
                    revision=EditingTaskRecord.revision + 1,
                    error_code=None,
                )
            )
            if not cast(CursorResult, fenced).rowcount:
                raise EditingFailure("EDITING_LEASE_LOST")
            for role, path, mime in artifacts:
                session.add(
                    EditingArtifactRecord(
                        id=str(uuid4()),
                        task_id=task_id,
                        role=role,
                        path=str(path),
                        mime=mime,
                        sha256=sha256(path),
                        bytes=path.stat().st_size,
                        duration_ms=validation["duration_ms"]
                        if role == "final"
                        else None,
                        validation=validation if role == "final" else {},
                    )
                )
            session.execute(
                update(EditingAttemptRecord)
                .where(EditingAttemptRecord.id == token)
                .values(status="completed", finished_at=datetime.now(UTC))
            )
            session.commit()
    except Exception as error:
        code = (
            error.code
            if isinstance(error, EditingFailure)
            else "EDITING_INTERNAL_ERROR"
        )
        status = "cancelled" if code == "EDITING_CANCELLED" else "failed"
        with factory() as session:
            session.execute(
                update(EditingTaskRecord)
                .where(
                    EditingTaskRecord.id == task_id,
                    EditingTaskRecord.owner_token == token,
                )
                .values(
                    status=status,
                    error_code=code,
                    owner_token=None,
                    lease_until=None,
                    revision=EditingTaskRecord.revision + 1,
                )
            )
            session.execute(
                update(EditingAttemptRecord)
                .where(
                    EditingAttemptRecord.id == token,
                    EditingAttemptRecord.status == "running",
                )
                .values(status=status, error_code=code, finished_at=datetime.now(UTC))
            )
            session.commit()
        # Fixed code only: no environment, credentials or raw provider response.
        atomic_json(
            root / "failure.json",
            {"code": code, "exception_type": type(error).__name__},
        )


@celery_app.task(
    name="polaris.process_editing_task", acks_late=True, reject_on_worker_lost=True
)
def process_editing_task(task_id: str) -> None:
    settings = Settings()
    engine, factory = build_database(settings.database_url)
    try:
        process(task_id, settings, factory)
    finally:
        engine.dispose()


def recover(factory: sessionmaker[Session]) -> int:
    now = int(datetime.now(UTC).timestamp())
    due = EditingTaskRecord.checkpoint["dispatch_not_before"].as_integer()
    with factory() as session:
        ids = list(
            session.scalars(
                select(EditingTaskRecord.id)
                .where(eligible(), or_(due.is_(None), due <= now))
                .order_by(EditingTaskRecord.created_at)
                .limit(100)
            )
        )
    return sum(enqueue(task_id, factory) for task_id in ids)


def enqueue(task_id: str, factory: sessionmaker[Session]) -> bool:
    """Reserve delivery in the DB before publishing; recover broker failures later.

    Duplicate deliveries are still fenced by process(). The bounded reservation
    avoids adding the same waiting job on every maintenance scan.
    """
    now = int(datetime.now(UTC).timestamp())
    with factory() as session:
        row = session.get(EditingTaskRecord, task_id)
        if not row or row.checkpoint.get("dispatch_not_before", 0) > now:
            return False
        reserved = session.execute(
            update(EditingTaskRecord)
            .execution_options(synchronize_session=False)
            .where(
                EditingTaskRecord.id == task_id,
                EditingTaskRecord.revision == row.revision,
                eligible(),
            )
            .values(
                checkpoint={**row.checkpoint, "dispatch_not_before": now + 300},
                revision=EditingTaskRecord.revision + 1,
            )
        )
        if not cast(CursorResult, reserved).rowcount:
            session.rollback()
            return False
        session.commit()
    try:
        with celery_app.connection_for_write(
            connect_timeout=3,
            transport_options={
                "socket_connect_timeout": 3,
                "socket_timeout": 3,
                "retry_on_timeout": False,
                "max_retries": 0,
            },
        ) as connection:
            celery_app.send_task(
                "polaris.process_editing_task",
                args=[task_id],
                queue="editing",
                retry=False,
                ignore_result=True,
                connection=connection,
            )
    except Exception:
        # No raw broker URL/credentials in logs. The durable row remains eligible.
        return False
    return True
