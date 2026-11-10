"""Separate semantic queue; preparation is free, billed response recovery is durable."""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from . import video_editing_planner as planner
from .celery_app import celery_app
from .config import Settings
from .database import build_database
from .errors import ApiError
from .motion_library import MOTION_SHA256, atomic_json, sha256, verify_package
from .motion_local_dependencies import dependency_state, local_dependencies
from .video_assistance_provider import VideoAssistanceProvider, planner_endpoint
from .video_editing_azl_panels import azl_blockers, azl_panel_windows
from .video_editing_browser_clocks import FRUIT_LIST_GROUP, FRUIT_LIST_TEMPLATE_ID
from .video_editing_catalog import (
    external_dependencies,
    planning_runtime_snapshot,
    unavailable_template_groups,
)
from .video_editing_crowd_scene import CROWD_GROUP
from .video_editing_cut_scenes import cut_scene_blockers
from .video_editing_cxbr import cxbr_blockers, cxbr_windows
from .video_editing_handoff_scenes import handoff_blockers
from .video_editing_hypit import PICTURE_GROUP, hypit_tools
from .video_editing_hypit_strips import LIVE_STAGE_GROUPS, SLANT_GROUP
from .video_editing_library_choice_store import stored_choice_snapshot
from .video_editing_materials import verify_material_cards
from .video_editing_native_content import WHY_GROUP
from .video_editing_native_plans import content_digest
from .video_editing_planning_store import FILES, execution_available, planning_root
from .video_editing_presenter_motion import motion_blockers, motion_word_windows
from .video_editing_story_panels import panel_blockers
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingPlanningAttemptRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_editing_template_materials import template_image_requirements
from .video_editing_transcript_store import read_transcript_artifact
from .video_editing_unified_scenes import (
    require_clean_unified_source,
    require_spoken_year,
)
from .video_editing_yy6_scenes import yy6_scene_inputs
from .video_editing_yy_openings import require_clean_yy_source


def hypit_template_blockers(
    settings: Settings, workspace_id: str, template: dict | None, source_subtitles: str
) -> dict[str, list[str]]:
    groups = {
        slot["group_id"]
        for slot in (template or {}).get("slots", [])
        if slot["group_id"] in LIVE_STAGE_GROUPS | {SLANT_GROUP, PICTURE_GROUP}
    }
    if not groups:
        return {}
    blockers = []
    if source_subtitles != "none":
        blockers.append("source-subtitles-must-be-none")
    try:
        hypit_tools(settings, workspace_id)
    except (OSError, ValueError):
        blockers.append("original-hypit-internal-runtime-unavailable")
    return {group: list(blockers) for group in sorted(groups)} if blockers else {}


def eligible() -> ColumnElement[bool]:
    return or_(
        EditingPlanningTaskRecord.status == "queued",
        (EditingPlanningTaskRecord.status == "running")
        & (EditingPlanningTaskRecord.lease_until < datetime.now(UTC)),
    )


def artifacts(root: Path, attempt: Path, mode: str) -> list[dict]:
    output = []
    for role, name in FILES.items():
        path = (
            root / "provider"
            if mode == "generate" and role not in {"lineage", "transcript"}
            else attempt
        ) / name
        if path.is_file() and path.resolve().is_relative_to(root):
            output.append(
                {
                    "role": role,
                    "path": str(path.resolve()),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
    return output


def verify_prepared(snapshot: dict, settings: Settings, prepared_id: str) -> None:
    parent = planning_root(settings, prepared_id)
    if not {"request", "request_evidence", "transcript"} <= {
        a["role"] for a in snapshot["prepared_artifacts"]
    }:
        raise ApiError(
            409, "EDITING_PREPARED_REQUEST_CHANGED", "准备记录缺少完整输入产物。"
        )
    for item in snapshot["prepared_artifacts"]:
        path = Path(item["path"]).resolve()
        if (
            not path.is_relative_to(parent)
            or not path.is_file()
            or path.stat().st_size != item["bytes"]
            or item["bytes"] > 4_000_000
            or sha256(path) != item["sha256"]
        ):
            raise ApiError(
                409,
                "EDITING_PREPARED_REQUEST_CHANGED",
                "已准备的请求产物发生变化，请恢复原产物。",
            )


def process(
    task_id: str,
    settings: Settings,
    factory: sessionmaker[Session],
    provider: VideoAssistanceProvider | None = None,
) -> None:
    token, now = str(uuid4()), datetime.now(UTC)
    with factory() as session:
        claimed = session.execute(
            update(EditingPlanningTaskRecord)
            .where(EditingPlanningTaskRecord.id == task_id, eligible())
            .values(
                status="running",
                stage="reading_inputs",
                owner_token=token,
                attempts=EditingPlanningTaskRecord.attempts + 1,
                revision=EditingPlanningTaskRecord.revision + 1,
                lease_until=now
                + timedelta(seconds=settings.video_editing_lease_seconds),
            )
        )
        if not cast(CursorResult, claimed).rowcount:
            session.rollback()
            return
        row = session.get(EditingPlanningTaskRecord, task_id)
        assert row is not None
        session.execute(
            update(EditingPlanningAttemptRecord)
            .where(
                EditingPlanningAttemptRecord.task_id == task_id,
                EditingPlanningAttemptRecord.status == "running",
            )
            .values(
                status="superseded",
                finished_at=now,
                error_code="EDITING_PLAN_LEASE_EXPIRED",
            )
        )
        session.add(
            EditingPlanningAttemptRecord(
                id=token,
                task_id=task_id,
                number=row.attempts,
                status="running",
                started_at=now,
            )
        )
        session.commit()
        mode, model, snapshot, prepared_id = (
            row.mode,
            row.model,
            row.snapshot,
            row.prepared_task_id,
        )
        base_id, artifact_id, artifact_sha = (
            row.base_task_id,
            row.base_transcript_artifact_id,
            row.base_transcript_sha256,
        )
        workspace_id, owner_id, project_id = (
            row.workspace_id,
            row.owner_user_id,
            row.project_id,
        )
        release, source_id = row.library_release, row.source_id
    root = planning_root(settings, task_id)
    attempt = root / "attempts" / token[:8]
    attempt.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {}

    def guard(stage: str | None = None) -> None:
        with factory() as session:
            saved = session.get(EditingPlanningTaskRecord, task_id)
            if not saved or saved.status != "running" or saved.owner_token != token:
                raise ApiError(
                    409, "EDITING_PLAN_LEASE_LOST", "规划任务已由其他尝试接手。"
                )
            if saved.cancel_requested:
                raise ApiError(409, "EDITING_PLAN_CANCELLED", "规划任务已取消。")
            values: dict[str, Any] = {
                "lease_until": datetime.now(UTC)
                + timedelta(seconds=settings.video_editing_lease_seconds)
            }
            if stage:
                values.update(
                    stage=stage, revision=EditingPlanningTaskRecord.revision + 1
                )
            renewed = session.execute(
                update(EditingPlanningTaskRecord)
                .execution_options(synchronize_session=False)
                .where(
                    EditingPlanningTaskRecord.id == task_id,
                    EditingPlanningTaskRecord.owner_token == token,
                    EditingPlanningTaskRecord.status == "running",
                    EditingPlanningTaskRecord.cancel_requested.is_(False),
                    EditingPlanningTaskRecord.lease_until >= datetime.now(UTC),
                )
                .values(**values)
            )
            if not cast(CursorResult, renewed).rowcount:
                raise ApiError(409, "EDITING_PLAN_LEASE_LOST", "规划租约已失效。")
            session.commit()

    try:
        guard()
        if not settings.video_editing_enabled or release != MOTION_SHA256:
            raise ApiError(
                503, "EDITING_PLANNING_DISABLED", "剪辑原库或任务配置不匹配。"
            )
        verify_package(settings.video_editing_library_dir)
        with factory() as session:
            base = session.get(EditingTaskRecord, base_id)
            source = session.get(EditingSourceRecord, source_id)
            record = session.get(EditingArtifactRecord, artifact_id)
            if (
                not base
                or not source
                or not record
                or any(
                    (r.workspace_id, r.owner_user_id, r.project_id)
                    != (workspace_id, owner_id, project_id)
                    for r in (base, source)
                )
                or base.source_id != source.id
                or record.sha256 != artifact_sha
                or source.media_sha256 != snapshot["source_sha256"]
            ):
                raise ApiError(
                    409, "EDITING_PLAN_SOURCE_CHANGED", "规划原片或转录身份不一致。"
                )
            transcript = read_transcript_artifact(
                record, base, settings.video_editing_tasks_dir
            )
            media_path = Path(source.media_path)
            if (
                not media_path.is_file()
                or sha256(media_path) != snapshot["source_sha256"]
            ):
                raise ApiError(
                    409,
                    "EDITING_PLAN_SOURCE_CHANGED",
                    "本期原片文件已变化，请恢复后再规划。",
                )
            if transcript.source_sha256 != snapshot["source_sha256"]:
                raise ApiError(
                    409, "EDITING_PLAN_SOURCE_CHANGED", "转录不属于已选原片。"
                )
            verified_materials = {}
            if not (root / "provider/semantic-submit-intent.json").exists():
                verified_materials = verify_material_cards(
                    session,
                    settings,
                    source,
                    snapshot["asset_cards"],
                    verify_bytes=True,
                )
            shutil.copyfile(record.path, attempt / FILES["transcript"])
            if (
                mode == "generate"
                and not (root / "provider/semantic-submit-intent.json").exists()
            ):
                current = stored_choice_snapshot(
                    session, workspace_id, owner_id, project_id
                )
                if current["sha256"] != snapshot["choice_snapshot"]["sha256"]:
                    raise ApiError(
                        409,
                        "EDITING_CHOICES_CHANGED_REPLAN_REQUIRED",
                        "项目选组已变化，请重新准备后核对。",
                    )
        atomic_json(
            attempt / FILES["lineage"],
            {
                "base_task_id": base_id,
                "base_transcript_artifact_id": artifact_id,
                "base_transcript_sha256": artifact_sha,
                "source_sha256": transcript.source_sha256,
                "text_status": transcript.text_status,
                "timing_review": transcript.timing_review,
                "recognition_calls": 0,
                "alignment_calls": 0,
                "mode": mode,
                "gateway": snapshot.get("gateway"),
                "choice_snapshot_sha256": snapshot["choice_snapshot"]["sha256"],
            },
        )
        guard("building_request")
        template = snapshot.get("overlay_template")
        runtime = snapshot.get("planning_runtime")
        if mode == "prepare":
            runtime = planning_runtime_snapshot(
                settings.video_editing_library_dir,
                settings.video_editing_tasks_dir
                / "_library-validation"
                / MOTION_SHA256[:12],
                local_dependencies(settings.video_editing_native_bindings_file),
                template,
            )
            runtime["unavailable_template_groups"].update(
                hypit_template_blockers(
                    settings, workspace_id, template, snapshot["source_subtitles"]
                )
            )
            require_clean_yy_source(
                template,
                snapshot["source_subtitles"],
                runtime["unavailable_template_groups"],
            )
            require_clean_unified_source(
                template,
                snapshot["source_subtitles"],
                runtime["unavailable_template_groups"],
            )
            require_spoken_year(
                template, transcript, runtime["unavailable_template_groups"]
            )
            cut_scene_blockers(
                template,
                snapshot["asset_cards"],
                runtime["unavailable_template_groups"],
            )
            panel_blockers(
                template,
                snapshot["asset_cards"],
                snapshot["source_sha256"],
                runtime["unavailable_template_groups"],
            )
            handoff_blockers(
                template,
                transcript,
                snapshot["asset_cards"],
                runtime["unavailable_template_groups"],
            )
            opening_inputs = yy6_scene_inputs(
                template,
                transcript,
                snapshot["asset_cards"],
                runtime["unavailable_template_groups"],
            )
            if opening_inputs:
                runtime["yy6_scene_inputs"] = opening_inputs
            motion_blockers(
                template,
                snapshot["source_subtitles"],
                snapshot["asset_cards"],
                snapshot["source_sha256"],
                runtime["unavailable_template_groups"],
            )
            azl_blockers(
                template,
                snapshot["source_subtitles"],
                snapshot["asset_cards"],
                snapshot["source_sha256"],
                runtime["unavailable_template_groups"],
            )
            panel_windows = azl_panel_windows(
                template,
                transcript,
                snapshot["asset_cards"],
                runtime["unavailable_template_groups"],
            )
            if panel_windows:
                runtime["azl_panel_windows"] = panel_windows
            cxbr_blockers(
                template,
                snapshot["source_subtitles"],
                snapshot["asset_cards"],
                snapshot["source_sha256"],
                runtime["unavailable_template_groups"],
            )
            broll_windows = cxbr_windows(
                template,
                transcript,
                snapshot["asset_cards"],
                runtime["unavailable_template_groups"],
            )
            if broll_windows:
                runtime["chenxi_broll_windows"] = broll_windows
            motion_windows = motion_word_windows(
                template,
                transcript,
                snapshot["asset_cards"],
                runtime["unavailable_template_groups"],
            )
            if motion_windows:
                runtime["presenter_motion_windows"] = motion_windows
            image_requirements = template_image_requirements(
                template, snapshot["asset_cards"], verified_materials
            )
            if image_requirements:
                runtime["project_image_requirements"] = image_requirements
            if any(
                row["group_id"] == WHY_GROUP
                and row["selected_distinct_images"] < row["required_distinct_images"]
                for row in image_requirements
            ):
                runtime["unavailable_template_groups"].setdefault(WHY_GROUP, []).append(
                    "current_question_props_required"
                )
            if any(
                row["group_id"] == CROWD_GROUP
                and not all(row["native_image_slot_ids"].values())
                for row in image_requirements
            ):
                runtime["unavailable_template_groups"].setdefault(
                    CROWD_GROUP, []
                ).append("current_crowd_image_slots_required")
            if (
                template
                and template["id"] == FRUIT_LIST_TEMPLATE_ID
                and "水果" not in "".join(token.text for token in transcript.tokens)
            ):
                runtime["unavailable_template_groups"].setdefault(
                    FRUIT_LIST_GROUP, []
                ).append("fruit-topic-missing-from-recorded-speech")
            snapshot = {**snapshot, "planning_runtime": runtime}
        body, evidence = planner.build_request(
            transcript,
            settings.video_editing_library_dir,
            model,
            snapshot["asset_cards"],
            snapshot["choice_snapshot"],
            template,
            runtime,
            public_copy_only=snapshot.get("public_copy_only", False),
        )
        result = {**evidence, "text_status": transcript.text_status}
        if mode == "prepare":
            atomic_json(attempt / FILES["request"], body)
            atomic_json(attempt / FILES["request_evidence"], evidence)
            status = "prepared"
        else:
            if not prepared_id:
                raise ApiError(
                    409, "EDITING_PREPARED_REQUEST_INVALID", "缺少准备记录。"
                )
            verify_prepared(snapshot, settings, prepared_id)
            if not (
                root / "provider/semantic-submit-intent.json"
            ).exists() and snapshot.get("gateway") != planner_endpoint(settings):
                raise ApiError(
                    409,
                    "EDITING_PLAN_ENDPOINT_CHANGED",
                    "规划网关已变化，请重新准备后核对。",
                )
            if evidence["request_sha256"] != snapshot["expected_request_sha256"]:
                raise ApiError(
                    409,
                    "EDITING_PLAN_INPUT_CHANGED",
                    "请求与已准备版本不一致，请重新准备。",
                )
            if not (
                root / "provider" / FILES["response"]
            ).is_file() and not execution_available(settings):
                raise ApiError(
                    503, "EDITING_PLANNING_DISABLED", "付费语义规划尚未开放。"
                )
            if (
                runtime
                and template
                and not (root / "provider/semantic-submit-intent.json").exists()
            ):
                external = external_dependencies(settings.video_editing_library_dir)
                bindings = local_dependencies(
                    settings.video_editing_native_bindings_file
                )
                current = unavailable_template_groups(
                    template,
                    lambda rid: dependency_state(
                        external.get(rid, {}), bindings.get(rid)
                    ),
                )
                current.update(
                    hypit_template_blockers(
                        settings, workspace_id, template, snapshot["source_subtitles"]
                    )
                )
                require_clean_yy_source(template, snapshot["source_subtitles"], current)
                require_clean_unified_source(
                    template, snapshot["source_subtitles"], current
                )
                require_spoken_year(template, transcript, current)
                cut_scene_blockers(template, snapshot["asset_cards"], current)
                panel_blockers(
                    template,
                    snapshot["asset_cards"],
                    snapshot["source_sha256"],
                    current,
                )
                handoff_blockers(template, transcript, snapshot["asset_cards"], current)
                yy6_scene_inputs(template, transcript, snapshot["asset_cards"], current)
                motion_blockers(
                    template,
                    snapshot["source_subtitles"],
                    snapshot["asset_cards"],
                    snapshot["source_sha256"],
                    current,
                )
                azl_blockers(
                    template,
                    snapshot["source_subtitles"],
                    snapshot["asset_cards"],
                    snapshot["source_sha256"],
                    current,
                )
                cxbr_blockers(
                    template,
                    snapshot["source_subtitles"],
                    snapshot["asset_cards"],
                    snapshot["source_sha256"],
                    current,
                )
                if current.keys() - runtime["unavailable_template_groups"].keys():
                    raise ApiError(
                        409,
                        "EDITING_TEMPLATE_DEPENDENCIES_CHANGED",
                        "准备后有模板运行条件发生变化，请重新准备并核对可选动效。",
                    )
            guard("planning")
            scoped = settings.model_copy(update={"video_editing_plan_model": model})
            plan = planner.generate(
                root / "provider",
                transcript,
                scoped,
                provider or VideoAssistanceProvider(scoped),
                snapshot["asset_cards"],
                snapshot["choice_snapshot"],
                expected_request_sha256=evidence["request_sha256"],
                guard=guard,
                template=template,
                runtime=runtime,
                public_copy_only=snapshot.get("public_copy_only", False),
            )
            atomic_json(root / "provider" / FILES["request_evidence"], evidence)
            result.update(
                semantic=plan.model_dump(mode="json"),
                semantic_content_sha256=content_digest(plan.model_dump(mode="json")),
                semantic_review="unreviewed",
                native_render_state="not_compiled",
            )
            positions = {t.id: i for i, t in enumerate(transcript.tokens)}
            result["aligned_spans"] = [
                {
                    "beat_id": beat.id,
                    "group_id": beat.group_id,
                    "text": "".join(
                        t.text
                        for t in transcript.tokens[
                            positions[beat.first_token_id] : positions[
                                beat.last_token_id
                            ]
                            + 1
                        ]
                    ),
                    "first_token_id": beat.first_token_id,
                    "last_token_id": beat.last_token_id,
                    "start_ms": transcript.tokens[
                        positions[beat.first_token_id]
                    ].start_ms,
                    "end_ms": transcript.tokens[positions[beat.last_token_id]].end_ms,
                    "timing_review": "unreviewed",
                }
                for beat in plan.beats
            ]
            status = "completed"
        guard("storing")
        result["artifacts"] = artifacts(root, attempt, mode)
        with factory() as session:
            saved = session.execute(
                update(EditingPlanningTaskRecord)
                .where(
                    EditingPlanningTaskRecord.id == task_id,
                    EditingPlanningTaskRecord.owner_token == token,
                    EditingPlanningTaskRecord.status == "running",
                    EditingPlanningTaskRecord.cancel_requested.is_(False),
                    EditingPlanningTaskRecord.lease_until >= datetime.now(UTC),
                )
                .values(
                    status=status,
                    stage=status,
                    owner_token=None,
                    lease_until=None,
                    error_code=None,
                    result=result,
                    snapshot=snapshot,
                    revision=EditingPlanningTaskRecord.revision + 1,
                )
            )
            if not cast(CursorResult, saved).rowcount:
                raise ApiError(409, "EDITING_PLAN_LEASE_LOST", "规划租约已失效。")
            session.execute(
                update(EditingPlanningAttemptRecord)
                .where(EditingPlanningAttemptRecord.id == token)
                .values(status=status, finished_at=datetime.now(UTC))
            )
            session.commit()
    except Exception as error:
        code = (
            error.code
            if isinstance(error, ApiError)
            else "EDITING_PLAN_CONTRACT_INVALID"
            if isinstance(error, (ValueError, KeyError, TypeError))
            else "EDITING_PLANNING_INTERNAL_ERROR"
        )
        status = "cancelled" if code == "EDITING_PLAN_CANCELLED" else "failed"
        result["artifacts"] = artifacts(root, attempt, mode)
        with factory() as session:
            session.execute(
                update(EditingPlanningTaskRecord)
                .where(
                    EditingPlanningTaskRecord.id == task_id,
                    EditingPlanningTaskRecord.owner_token == token,
                )
                .values(
                    status=status,
                    stage=status,
                    error_code=code,
                    result=result,
                    owner_token=None,
                    lease_until=None,
                    revision=EditingPlanningTaskRecord.revision + 1,
                )
            )
            session.execute(
                update(EditingPlanningAttemptRecord)
                .where(
                    EditingPlanningAttemptRecord.id == token,
                    EditingPlanningAttemptRecord.status == "running",
                )
                .values(status=status, error_code=code, finished_at=datetime.now(UTC))
            )
            session.commit()
        atomic_json(
            attempt / "failure.json",
            {"code": code, "exception_type": type(error).__name__},
        )


def recover(factory: sessionmaker[Session]) -> int:
    now = int(datetime.now(UTC).timestamp())
    due = EditingPlanningTaskRecord.checkpoint["dispatch_not_before"].as_integer()
    with factory() as session:
        ids = list(
            session.scalars(
                select(EditingPlanningTaskRecord.id)
                .where(eligible(), or_(due.is_(None), due <= now))
                .order_by(EditingPlanningTaskRecord.created_at)
                .limit(100)
            )
        )
    return sum(enqueue(task_id, factory) for task_id in ids)


def enqueue(task_id: str, factory: sessionmaker[Session]) -> bool:
    now = int(datetime.now(UTC).timestamp())
    with factory() as session:
        row = session.get(EditingPlanningTaskRecord, task_id)
        if not row or row.checkpoint.get("dispatch_not_before", 0) > now:
            return False
        saved = session.execute(
            update(EditingPlanningTaskRecord)
            .where(
                EditingPlanningTaskRecord.id == task_id,
                EditingPlanningTaskRecord.revision == row.revision,
                eligible(),
            )
            .values(
                checkpoint={**row.checkpoint, "dispatch_not_before": now + 300},
                revision=EditingPlanningTaskRecord.revision + 1,
            )
        )
        if not cast(CursorResult, saved).rowcount:
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
                "polaris.process_editing_planning_task",
                args=[task_id],
                queue="editing-planning",
                retry=False,
                ignore_result=True,
                connection=connection,
            )
    except Exception:
        return False
    return True


@celery_app.task(
    name="polaris.process_editing_planning_task",
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_editing_planning_task(task_id: str) -> None:
    settings = Settings()
    engine, factory = build_database(settings.database_url)
    try:
        process(task_id, settings, factory)
    finally:
        engine.dispose()
