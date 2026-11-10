"""Separate editing queue with durable DB claims, cancellation and stale-run fences."""

import hashlib
import importlib.metadata
import json
import shutil
from collections.abc import Callable
from contextlib import suppress
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
from .errors import ApiError
from .motion_library import (
    MOTION_SHA256,
    atomic_json,
    read_json,
    sha256,
    verify_package,
)
from .video_editing_contracts import NativeRenderEdits, SemanticPlan, Transcript
from .video_editing_delivery_checkpoint import (
    DeliveryFile,
    checkpoint_for,
    compiled_digest,
    delivery_file,
    restore_delivery,
)
from .video_editing_episode_compiler import EpisodeRecipeBundle, compile_episode
from .video_editing_image_edits import apply_image_edits, resolve_image_edits
from .video_editing_materials import PREFIX, project_material_files
from .video_editing_native_layout import verified_effect_occurrences
from .video_editing_native_plans import frozen_plan_snapshot
from .video_editing_overlay_templates import MIN_OVERLAY_TYPES, motion_counts
from .video_editing_pipeline import (
    EditingFailure,
    compile_baseline,
    measured_source_frame,
    native_export,
    prepare,
    prepare_material_frame_clocks,
    prepare_presenter_frame_clock,
    run,
    validate_result,
)
from .video_editing_planning_provenance import verify_render_provenance
from .video_editing_preview import build_preview
from .video_editing_preview_base import preview_base_attempt
from .video_editing_source_lineage import (
    generation_source_receipt,
    script_reference,
    source_origin,
)
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingAttemptRecord,
    EditingNativePlanRecord,
    EditingSourceRecord,
    EditingTaskRecord,
    EditingTranscriptRevisionRecord,
)
from .video_editing_transcript_store import MAX_TRANSCRIPT_BYTES
from .video_studio_models import VideoScriptVersionRecord
from .video_writing_provenance import script_digest


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


def load_transcript(
    task_id: str,
    root: Path,
    prepared: dict,
    snapshot: dict[str, Any],
    settings: Settings,
    guard: Callable[..., None],
    stage: Callable[..., None],
) -> Transcript:
    """Existing recognition/alignment and exact-byte recovery path."""
    correction = snapshot["correction"]
    expected_provider: str = settings.video_editing_asr_provider
    expected_model = settings.video_editing_asr_model
    profile: str | None
    if correction:
        if not settings.video_editing_alignment_enabled:
            raise EditingFailure("EDITING_ALIGNMENT_DISABLED")
        from .video_editing_alignment import ALIGNMENT_MANIFEST, PROCESSING_VERSION
        from .video_editing_funasr import bundle_identity

        base_path = Path(correction["base_path"]).resolve()
        if (
            not base_path.is_relative_to(
                (
                    settings.video_editing_tasks_dir / correction["base_task_id"]
                ).resolve()
            )
            or not base_path.is_file()
            or sha256(base_path) != correction["base_sha256"]
            or hashlib.sha256(correction["text"].encode()).hexdigest()
            != correction["text_sha256"]
            or prepared["source_sha256"] != correction["source_sha256"]
            or prepared["audio_sha256"] != correction["audio_sha256"]
        ):
            raise EditingFailure("EDITING_ALIGNMENT_SOURCE_MISMATCH")
        identity = bundle_identity(
            settings.video_editing_alignment_model_dir,
            manifest_path=ALIGNMENT_MANIFEST,
        )
        expected_provider, expected_model = (
            "funasr-fa-zh",
            str(settings.video_editing_alignment_model_dir),
        )
        profile = hashlib.sha256(
            json.dumps(
                {
                    "correction": correction,
                    "model_identity": identity,
                    "funasr_version": importlib.metadata.version("funasr"),
                    "processing": PROCESSING_VERSION,
                    "device": settings.video_editing_asr_device,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        stage("aligning")
    else:
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
            and candidate.duration_ms == prepared["duration_ms"]
            and candidate.model == expected_model
            and candidate.provider == expected_provider
            and candidate.text_revision_id
            == snapshot["options"].get("transcript_revision_id")
        ):
            if correction:
                evidence = cached.get("alignment_evidence", {})
                names = {
                    "alignment-input.txt",
                    "alignment-raw.json",
                    "alignment-receipt.json",
                    "parent-transcript.json",
                }
                if set(evidence) == names and all(
                    Path(item["path"])
                    .resolve()
                    .is_relative_to(
                        (settings.video_editing_tasks_dir / task_id).resolve()
                    )
                    and Path(item["path"]).is_file()
                    and sha256(Path(item["path"])) == item["sha256"]
                    for item in evidence.values()
                ):
                    for name, item in evidence.items():
                        shutil.copyfile(item["path"], root / name)
                    transcript = candidate
            else:
                transcript = candidate
    if transcript is None:
        if correction:
            shutil.copyfile(correction["base_path"], root / "parent-transcript.json")
            atomic_json(
                root / "alignment-config.json",
                {
                    "model": expected_model,
                    "device": settings.video_editing_asr_device,
                    "parent_sha256": correction["base_sha256"],
                    "text": correction["text"],
                    "revision_id": correction["id"],
                    "text_status": correction["text_status"],
                },
            )
        else:
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
                "app.video_editing_alignment"
                if correction
                else "app.video_editing_asr",
                "--instance",
                str(root),
            ],
            root,
            settings,
            guard,
            "alignment" if correction else "asr",
        )
        transcript = Transcript.model_validate(read_json(root / "transcript.json"))
    else:
        # Preserve the exact immutable bytes referenced by the cached receipt.
        shutil.copyfile(cached["path"], root / "transcript.json")
    stage(
        "storing" if snapshot["options"].get("mode") == "transcript" else "compiling",
        transcript={
            "path": str(root / "transcript.json"),
            "sha256": sha256(root / "transcript.json"),
            "profile": profile,
            **(
                {
                    "alignment_evidence": {
                        name: {
                            "path": str(root / name),
                            "sha256": sha256(root / name),
                        }
                        for name in (
                            "alignment-input.txt",
                            "alignment-raw.json",
                            "alignment-receipt.json",
                            "parent-transcript.json",
                        )
                    }
                }
                if correction
                else {}
            ),
        },
    )
    return transcript


def load_plan_transcript(
    root: Path,
    prepared: dict,
    plan: dict[str, Any],
    settings: Settings,
) -> Transcript:
    path = Path(plan["base_transcript_path"]).resolve()
    if (
        not path.is_relative_to(
            (settings.video_editing_tasks_dir / plan["base_task_id"]).resolve()
        )
        or not path.is_file()
        or path.stat().st_size > MAX_TRANSCRIPT_BYTES
        or sha256(path) != plan["base_transcript_sha256"]
        or plan["source_sha256"] != prepared["source_sha256"]
        or plan["audio_sha256"] != prepared["audio_sha256"]
    ):
        raise EditingFailure("EDITING_PLAN_SOURCE_CHANGED")
    transcript = Transcript.model_validate(read_json(path))
    if (
        transcript.source_sha256 != prepared["source_sha256"]
        or transcript.audio_sha256 != prepared["audio_sha256"]
        or transcript.duration_ms != prepared["duration_ms"]
    ):
        raise EditingFailure("EDITING_PLAN_SOURCE_CHANGED")
    shutil.copyfile(path, root / "transcript.json")
    atomic_json(
        root / "native-plan-lineage.json",
        {
            "id": plan["id"],
            "planning_origin": plan["origin"],
            "base_task_id": plan["base_task_id"],
            "base_transcript_sha256": plan["base_transcript_sha256"],
            "transcript_reused_exactly": True,
            "recognition_calls": 0,
            "alignment_calls": 0,
            "planning_calls": 0,
            "planning_provenance": plan.get("planning_provenance"),
            **(
                {
                    "project_materials": [
                        {"id": aid, "sha256": asset["sha256"], "kind": asset["kind"]}
                        for aid, asset in sorted(plan["asset_files"].items())
                        if aid.startswith(PREFIX)
                    ]
                }
                if any(aid.startswith(PREFIX) for aid in plan.get("asset_files", {}))
                else {}
            ),
        },
    )
    return transcript


def stage_plan_materials(
    session: Session,
    root: Path,
    plan: dict,
    settings: Settings,
    guard: Callable[[], None],
    source_only_beats: set[str] | None = None,
) -> dict:
    assets = plan["asset_files"]
    used = {
        aid
        for beat in plan["semantic"]["beats"]
        if not source_only_beats or beat["id"] not in source_only_beats
        for aid in beat["asset_ids"]
    }
    frozen = {
        aid: asset
        for aid, asset in assets.items()
        if aid.startswith(PREFIX) and (not source_only_beats or aid in used)
    }
    if not frozen:
        return assets
    source = session.get(EditingSourceRecord, plan["source_id"])
    if not source or (source.workspace_id, source.owner_user_id, source.project_id) != (
        plan["workspace_id"],
        plan["owner_user_id"],
        plan["project_id"],
    ):
        raise EditingFailure("EDITING_MATERIAL_CHANGED")
    try:
        if project_material_files(session, settings, source, set(frozen)) != frozen:
            raise EditingFailure("EDITING_MATERIAL_CHANGED")
        session.rollback()
        staged = dict(assets)
        for aid in frozen.keys() & used:
            asset = frozen[aid]
            origin = Path(asset["path"])
            target = root / "input" / "materials" / (aid + origin.suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            length = 0
            with origin.open("rb") as src, target.open("xb") as dst:
                while block := src.read(1024 * 1024):
                    guard()
                    length += len(block)
                    if length > asset["bytes"]:
                        raise EditingFailure("EDITING_MATERIAL_CHANGED")
                    digest.update(block)
                    dst.write(block)
            if length != asset["bytes"] or digest.hexdigest() != asset["sha256"]:
                raise EditingFailure("EDITING_MATERIAL_CHANGED")
            staged[aid] = {**asset, "path": str(target)}
        return staged
    except (ApiError, OSError, ValueError) as error:
        raise EditingFailure("EDITING_MATERIAL_CHANGED") from error


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
        base_attempt = preview_base_attempt(session, settings, source, row.options)
        snapshot: dict[str, Any] = {
            "source_path": source.media_path,
            "source_sha256": source.media_sha256,
            "request_hash": row.request_hash,
            "options": row.options,
            "checkpoint": row.checkpoint,
            "library_release": row.library_release,
            "confirmed_version_id": source.confirmed_version_id,
            "source_origin": source_origin(source),
            "generation_lineage": source.details.get("generation_lineage"),
        }
        version = (
            session.get(VideoScriptVersionRecord, source.confirmed_version_id)
            if source.confirmed_version_id
            else None
        )
        snapshot["reference"] = (
            script_reference(version)
            if snapshot["generation_lineage"]
            else version.snapshot.get("draft", {}).get("text")
            if version
            else None
        )
        snapshot["confirmed_version_valid"] = not source.confirmed_version_id or bool(
            version
            and version.project_id == source.project_id
            and version.kind == "confirmed"
        )
        snapshot["confirmed_writing_origin"] = (
            version.writing_origin if version else None
        )
        snapshot["native_plan"] = None
        plan_id = row.options.get("native_plan_id")
        if plan_id:
            plan = session.get(EditingNativePlanRecord, plan_id)
            if (
                plan
                and plan.source_id == row.source_id
                and plan.project_id == row.project_id
                and plan.workspace_id == row.workspace_id
                and plan.owner_user_id == row.owner_user_id
            ):
                artifact = session.get(
                    EditingArtifactRecord, plan.base_transcript_artifact_id
                )
                if artifact:
                    # Fail within the fenced try block if the snapshot is invalid.
                    with suppress(ValueError, KeyError, TypeError):
                        snapshot["native_plan"] = frozen_plan_snapshot(plan, artifact)
        snapshot["correction"] = None
        correction_id = row.options.get("transcript_revision_id")
        if correction_id:
            correction = session.get(EditingTranscriptRevisionRecord, correction_id)
            if (
                correction
                and correction.source_id == row.source_id
                and correction.workspace_id == row.workspace_id
                and correction.owner_user_id == row.owner_user_id
                and correction.project_id == row.project_id
            ):
                base_artifact = session.get(
                    EditingArtifactRecord, correction.base_transcript_artifact_id
                )
                if (
                    base_artifact
                    and base_artifact.role == "transcript"
                    and base_artifact.task_id == correction.base_task_id
                    and base_artifact.sha256 == correction.base_transcript_sha256
                ):
                    snapshot["correction"] = {
                        "id": correction.id,
                        "text": correction.corrected_text,
                        "text_sha256": correction.text_sha256,
                        "text_status": correction.text_status,
                        "base_path": base_artifact.path,
                        "base_sha256": correction.base_transcript_sha256,
                        "base_task_id": correction.base_task_id,
                        "source_sha256": correction.details.get("source_sha256"),
                        "audio_sha256": correction.details.get("audio_sha256"),
                    }
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

    def publish(
        files: dict[str, DeliveryFile],
        media_validation: dict,
        *,
        status: str,
        ready_stage: str,
    ) -> None:
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
                    status=status,
                    stage=ready_stage,
                    owner_token=None,
                    lease_until=None,
                    revision=EditingTaskRecord.revision + 1,
                    error_code=None,
                )
            )
            if not cast(CursorResult, fenced).rowcount:
                raise EditingFailure("EDITING_LEASE_LOST")
            for role, file in files.items():
                media = media_validation.get(role, {})
                session.add(
                    EditingArtifactRecord(
                        id=str(uuid4()),
                        task_id=task_id,
                        role=role,
                        path=str(file.path),
                        mime=file.mime,
                        sha256=file.sha256,
                        bytes=file.bytes,
                        duration_ms=media.get("duration_ms"),
                        validation=media,
                    )
                )
            session.execute(
                update(EditingAttemptRecord)
                .where(EditingAttemptRecord.id == token)
                .values(status="completed", finished_at=datetime.now(UTC))
            )
            session.commit()

    try:
        guard(True)
        if not settings.video_editing_enabled:
            raise EditingFailure("EDITING_DISABLED")
        correction = snapshot["correction"]
        if snapshot["options"].get("transcript_revision_id") and not correction:
            raise EditingFailure("EDITING_TRANSCRIPT_REVISION_NOT_FOUND")
        if snapshot["options"].get("source_subtitles") == "unknown":
            raise EditingFailure("EDITING_SOURCE_SUBTITLES_REVIEW_REQUIRED")
        if snapshot["library_release"] != MOTION_SHA256:
            raise EditingFailure("EDITING_LIBRARY_CHANGED")
        lineage = snapshot["generation_lineage"]
        if lineage and (
            not snapshot["confirmed_version_valid"]
            or script_digest(snapshot["reference"]) != lineage["script_sha256"]
            or (
                "writing_origin" in lineage
                and lineage["writing_origin"] != snapshot["confirmed_writing_origin"]
            )
        ):
            raise EditingFailure("EDITING_GENERATION_SCRIPT_CHANGED")
        verify_package(settings.video_editing_library_dir)
        prepared = prepare(
            Path(snapshot["source_path"]),
            snapshot["source_sha256"],
            root,
            settings,
            guard,
        )
        if lineage:
            atomic_json(
                root / "source-receipt.json",
                generation_source_receipt(
                    snapshot["source_origin"], lineage, prepared, settings, guard
                ),
            )
        native_plan = snapshot["native_plan"]
        if snapshot["options"].get("mode") == "native_plan":
            if not settings.video_editing_native_plan_enabled or not native_plan:
                raise EditingFailure("EDITING_NATIVE_PLAN_NOT_FOUND")
            transcript = load_plan_transcript(root, prepared, native_plan, settings)
            with factory() as session:
                try:
                    verified_plan_hash = verify_render_provenance(
                        session, settings, native_plan
                    )
                except (ApiError, ValueError, KeyError, TypeError) as error:
                    raise EditingFailure(
                        "EDITING_PLANNER_PROVENANCE_REQUIRED"
                    ) from error
            stage("compiling", native_plan_id=native_plan["id"])
            semantic = SemanticPlan.model_validate(native_plan["semantic"])
            raw_edits = snapshot["options"].get("native_edits")
            try:
                edits = (
                    NativeRenderEdits.model_validate(raw_edits) if raw_edits else None
                )
            except ValueError as error:
                raise EditingFailure("EDITING_NATIVE_EDITS_INVALID") from error
            with factory() as session:
                material_plan = native_plan
                if edits and edits.image_edits:
                    source = session.get(EditingSourceRecord, native_plan["source_id"])
                    if source is None:
                        raise EditingFailure("EDITING_MATERIAL_CHANGED")
                    try:
                        merged = resolve_image_edits(
                            session,
                            settings,
                            source,
                            edits.image_edits,
                            native_plan["asset_files"],
                        )
                    except ApiError as error:
                        raise EditingFailure("EDITING_MATERIAL_CHANGED") from error
                    try:
                        effective, _ = apply_image_edits(
                            edits.image_edits,
                            semantic,
                            native_plan["recipes"],
                            merged,
                            transcript,
                        )
                    except (ValueError, KeyError) as error:
                        raise EditingFailure("EDITING_IMAGE_EDIT_INVALID") from error
                    material_plan = {
                        **native_plan,
                        "semantic": effective.model_dump(mode="json"),
                        "asset_files": merged,
                    }
                assets = stage_plan_materials(
                    session,
                    root,
                    material_plan,
                    settings,
                    guard,
                    set(edits.source_only_beat_ids) if edits else None,
                )
            compile_episode(
                root,
                prepared,
                transcript,
                semantic,
                EpisodeRecipeBundle.model_validate(native_plan["recipes"]),
                assets,
                snapshot["options"],
                settings,
                native_plan["choice_snapshot"],
                verified_gateway_plan_hash=verified_plan_hash,
                workspace_id=native_plan["workspace_id"],
                guard=guard,
            )
        else:
            transcript = load_transcript(
                task_id, root, prepared, snapshot, settings, guard, stage
            )
            if snapshot["options"].get("mode") == "transcript":
                text_file = delivery_file(root / "transcript.json")
                audio_file = delivery_file(root / "input/speech.wav")
                if not transcript.tokens:
                    raise EditingFailure("EDITING_NO_SPEECH_RECOGNIZED")
                if (
                    text_file.bytes > MAX_TRANSCRIPT_BYTES
                    or audio_file.sha256 != prepared["audio_sha256"]
                    or transcript.audio_sha256 != audio_file.sha256
                    or transcript.source_sha256 != prepared["source_sha256"]
                    or transcript.duration_ms != prepared["duration_ms"]
                ):
                    raise EditingFailure("EDITING_TRANSCRIPT_CHANGED")
                transcript_files = {
                    "transcript": text_file,
                    "transcript_audio": audio_file,
                }
                if lineage:
                    transcript_files["source_receipt"] = delivery_file(
                        root / "source-receipt.json"
                    )
                if correction:
                    transcript_files["alignment_receipt"] = delivery_file(
                        root / "alignment-receipt.json"
                    )
                clock = prepared["clock"]
                offset = clock["audio_offset_ms"]
                publish(
                    transcript_files,
                    {
                        "transcript": {
                            "duration_ms": transcript.duration_ms,
                            "analysis_audio_offset_ms": offset,
                            "source_frame": measured_source_frame(
                                prepared["probe"]
                            ).model_dump(),
                        },
                        "transcript_audio": {
                            "duration_ms": clock["analysis_audio_end_ms"] - offset,
                        },
                    },
                    status="completed",
                    ready_stage="transcript_ready",
                )
                return
            compile_baseline(root, prepared, transcript, snapshot["options"], settings)
        review_first = snapshot["options"].get("delivery") == "preview_first"
        final_role = "staged_final" if review_first else "final"
        receipts = {
            "transcript": "transcript.json",
            "caption_anchors": "caption-anchors.json",
            "caption_receipt": "caption-segmentation.json",
            "caption_layout": "caption-adapter-layout.json",
            "receipt": "validation.json",
        }
        if lineage:
            receipts["source_receipt"] = "source-receipt.json"
        if native_plan:
            receipts.update(
                semantic_plan="semantic-plan.json",
                compile_receipt="compile-diagnostics.json",
                plan_lineage="native-plan-lineage.json",
            )
        if correction:
            receipts["alignment_receipt"] = "alignment-receipt.json"
        prepare_presenter_frame_clock(root, prepared, settings, guard)
        if native_plan:
            prepare_material_frame_clocks(root, settings, guard)
        compiled_sha = compiled_digest(root, snapshot["request_hash"])
        restored = restore_delivery(
            snapshot["checkpoint"].get("validated_delivery"),
            root.parent,
            compiled_sha,
            prepared["source_sha256"],
            final_role,
            set(receipts),
            guard,
        )
        reused = []
        if restored is None:
            stage("rendering", render_plan_sha256=sha256(root / "episode.json"))
            atomic_json(
                root / "native-shot-plan.json",
                {
                    "compiled_sha256": compiled_sha,
                    **(
                        {"preview_base_attempt": str(base_attempt)}
                        if base_attempt
                        else {}
                    ),
                },
            )
            final = native_export(root, settings, guard)
            stage("validating")
            validation = validate_result(final, prepared, root, settings, guard)
            if review_first:
                try:
                    delivery = read_json(final.with_suffix(".delivery.json"))
                    if delivery["sha256"] != validation["sha256"]:
                        raise ValueError("Original composition identity changed")
                    occurrences = verified_effect_occurrences(
                        read_json(root / "episode.json"), delivery
                    )
                    counts = motion_counts(occurrences)
                    if counts["distinct_groups"] < MIN_OVERLAY_TYPES:
                        raise ValueError("Insufficient distinct visible native effects")
                except (ValueError, KeyError, TypeError, OSError):
                    raise EditingFailure(
                        "EDITING_CONTINUOUS_COMBINATION_REQUIRED"
                    ) from None
                validation["visible_effect_groups"] = sorted(set(occurrences))
                validation["motion_counts"] = counts
                atomic_json(root / "validation.json", validation)
            if validation.get("native_mix_validation") == "passed":
                receipts["audio_receipt"] = "audio-validation.json"
            if (root / "layout/adapter-review.json").is_file():
                receipts["layout_receipt"] = "layout/adapter-review.json"
            files = {
                final_role: delivery_file(final),
                **{role: delivery_file(root / path) for role, path in receipts.items()},
            }
            if files[final_role].sha256 != validation["sha256"]:
                raise EditingFailure("EDITING_PREVIEW_ARTIFACT_CHANGED")
            media_validation = {final_role: validation}
        else:
            files, media_validation = restored
            reused = list(media_validation)
        if review_first and "preview" not in files:
            stage(
                "building_preview",
                validated_delivery=checkpoint_for(root.parent, compiled_sha, files),
                reused_delivery=reused,
            )
            (root / "outputs").mkdir(exist_ok=True)
            preview, preview_receipt = build_preview(
                files[final_role].path,
                root,
                media_validation[final_role],
                settings,
                guard,
            )
            files["preview"] = delivery_file(preview)
            if files["preview"].sha256 != preview_receipt["sha256"]:
                raise EditingFailure("EDITING_PREVIEW_ARTIFACT_CHANGED")
            files["preview_receipt"] = delivery_file(root / "preview-validation.json")
            media_validation["preview"] = preview_receipt
        stage(
            "storing",
            validated_delivery=checkpoint_for(root.parent, compiled_sha, files),
            reused_delivery=reused,
        )
        publish(
            files,
            media_validation,
            status="awaiting_review" if review_first else "completed",
            ready_stage="preview_ready" if review_first else "completed",
        )
    except Exception as error:
        code = (
            error.code
            if isinstance(error, EditingFailure)
            else "EDITING_INTERNAL_ERROR"
        )
        status = "cancelled" if code == "EDITING_CANCELLED" else "failed"
        with factory() as session:
            failure_values: dict[str, Any] = {}
            if isinstance(error, EditingFailure) and error.layout_findings:
                saved = session.get(EditingTaskRecord, task_id)
                if saved is not None:
                    failure_values["checkpoint"] = {
                        **saved.checkpoint,
                        "layout_findings": [
                            item.model_dump() for item in error.layout_findings
                        ],
                    }
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
                    **failure_values,
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
