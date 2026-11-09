"""Freeze reviewed-input identities for native render jobs, not quality approval."""

import hashlib
import json
from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .errors import ApiError
from .motion_library import MOTION_SHA256
from .video_editing_contracts import EditingOptions, SemanticPlan
from .video_editing_episode_compiler import EpisodeRecipeBundle
from .video_editing_library_choice_store import stored_choice_snapshot
from .video_editing_materials import project_material_files, verify_material_cards
from .video_editing_planner import validate_plan
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingNativePlanRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_editing_transcript_store import read_transcript_artifact
from .video_studio_models import VideoProjectRecord


def content_digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def plan_response(row: EditingNativePlanRecord, settings: Settings) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "source_id": row.source_id,
        "base_task_id": row.base_task_id,
        "base_transcript_artifact_id": row.base_transcript_artifact_id,
        "library_release": row.library_release,
        "origin": row.origin,
        "state": "semantic_contract_validated",
        "audience_question": row.semantic["audience_question"],
        "beats": row.details["beats"],
        "warnings": row.semantic.get("warnings", []),
        "missing_materials": row.semantic.get("missing_materials", []),
        "text_status": row.details["text_status"],
        "source_subtitles": row.details["source_subtitles"],
        "caption_font_id": row.recipes["design"]["caption_font_id"],
        "choice_snapshot_sha256": row.choice_snapshot["sha256"],
        "semantic_review": "unreviewed",
        "render_available": settings.video_editing_native_plan_enabled,
        "created_at": row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
    }


def source_assets(source: EditingSourceRecord) -> dict[str, dict[str, Any]]:
    # The only automatic material is this same project's actual raw presenter.
    # It is deliberately not declared as product/action evidence.
    return {
        "source-" + source.id: {
            "path": source.media_path,
            "sha256": source.media_sha256,
            "kind": "original_video",
            "semantic_use": "本期原片说话人，不是商品实拍证据",
            "viewed_identity": None,
            "source": source.kind,
            "license": "user-provided current project source; local processing only",
        }
    }


def register_operator_plan(
    session: Session,
    settings: Settings,
    workspace_id: str,
    owner_user_id: str,
    base_task_id: str,
    request_id: str,
    semantic: SemanticPlan,
    recipes: EpisodeRecipeBundle,
) -> EditingNativePlanRecord:
    """Operator-only service/CLI. No public upload of executable native recipes."""
    if recipes.planning_origin != "operator_candidate":
        raise ApiError(
            422, "EDITING_PLANNER_PROVENANCE_REQUIRED", "人工导入不能声明腾力模型来源。"
        )
    return _register_plan(
        session,
        settings,
        workspace_id,
        owner_user_id,
        base_task_id,
        request_id,
        semantic,
        recipes,
    )


def register_gateway_plan(
    session: Session,
    settings: Settings,
    workspace_id: str,
    owner_user_id: str,
    planning_task_id: str,
    request_id: str,
    recipes: EpisodeRecipeBundle,
) -> EditingNativePlanRecord:
    """Trusted adapter/CLI only; semantic JSON always comes from the server job."""
    from .video_editing_planning_provenance import verify_gateway_planning

    verified = verify_gateway_planning(
        session, settings, workspace_id, owner_user_id, planning_task_id
    )
    if recipes.planning_origin != "tengli_gateway":
        raise ApiError(
            422, "EDITING_PLANNER_PROVENANCE_REQUIRED", "配方来源需与已捕获规划一致。"
        )
    current = stored_choice_snapshot(
        session, workspace_id, owner_user_id, verified.task.project_id
    )
    if current != verified.task.snapshot["choice_snapshot"]:
        raise ApiError(
            409,
            "EDITING_CHOICES_CHANGED_REPLAN_REQUIRED",
            "选组已变化，请重新准备并核对规划。",
        )
    return _register_plan(
        session,
        settings,
        workspace_id,
        owner_user_id,
        verified.task.base_task_id,
        request_id,
        verified.semantic,
        recipes,
        verified.lineage,
        verified.task.snapshot["asset_cards"],
    )


def _register_plan(
    session: Session,
    settings: Settings,
    workspace_id: str,
    owner_user_id: str,
    base_task_id: str,
    request_id: str,
    semantic: SemanticPlan,
    recipes: EpisodeRecipeBundle,
    planning_provenance: dict[str, Any] | None = None,
    planning_cards: list[dict] | None = None,
) -> EditingNativePlanRecord:
    semantic_data, recipe_data = (
        semantic.model_dump(mode="json"),
        recipes.model_dump(mode="json"),
    )
    fingerprint = content_digest(
        {
            "base_task_id": base_task_id,
            "semantic": semantic_data,
            "recipes": recipe_data,
            **(
                {"planning_provenance": planning_provenance}
                if planning_provenance
                else {}
            ),
        }
    )
    previous = session.scalar(
        select(EditingNativePlanRecord).where(
            EditingNativePlanRecord.workspace_id == workspace_id,
            EditingNativePlanRecord.owner_user_id == owner_user_id,
            EditingNativePlanRecord.request_id == request_id,
        )
    )
    if previous:
        if previous.request_hash != fingerprint:
            raise ApiError(
                409, "EDITING_NATIVE_PLAN_REQUEST_REUSED", "请求编号已用于另一份编排。"
            )
        return previous
    task = session.get(EditingTaskRecord, base_task_id)
    if (
        not task
        or task.workspace_id != workspace_id
        or task.owner_user_id != owner_user_id
    ):
        raise ApiError(404, "EDITING_NOT_FOUND", "未找到本项目的原剪辑任务。")
    source = session.get(EditingSourceRecord, task.source_id)
    project = session.get(VideoProjectRecord, task.project_id)
    if (
        not source
        or source.workspace_id != workspace_id
        or source.owner_user_id != owner_user_id
        or source.project_id != task.project_id
        or not project
        or project.workspace_id != workspace_id
        or project.owner_user_id != owner_user_id
    ):
        raise ApiError(404, "EDITING_SOURCE_NOT_FOUND", "未找到对应的视频源。")
    artifact = session.scalar(
        select(EditingArtifactRecord).where(
            EditingArtifactRecord.task_id == task.id,
            EditingArtifactRecord.role == "transcript",
        )
    )
    transcript = read_transcript_artifact(
        artifact, task, settings.video_editing_tasks_dir
    )
    assert artifact is not None
    if (
        recipes.library_release != MOTION_SHA256
        or recipes.transcript_sha256 != artifact.sha256
        or recipes.source_sha256 != source.media_sha256
        or transcript.source_sha256 != source.media_sha256
    ):
        raise ApiError(
            409, "EDITING_PLAN_SOURCE_CHANGED", "编排与原片或转录版本不一致。"
        )
    if task.options.get("source_subtitles") not in {"none", "present"}:
        raise ApiError(
            409, "EDITING_SOURCE_SUBTITLES_REVIEW_REQUIRED", "请先确认原片字幕状态。"
        )
    choice_snapshot = stored_choice_snapshot(
        session, workspace_id, owner_user_id, task.project_id
    )
    assets = source_assets(source)
    if planning_cards is not None:
        assets.update(
            verify_material_cards(
                session, settings, source, planning_cards, verify_bytes=False
            )
        )
    else:
        assets.update(
            project_material_files(
                session,
                settings,
                source,
                {aid for beat in semantic.beats for aid in beat.asset_ids},
            )
        )
    validate_plan(
        semantic,
        transcript,
        settings.video_editing_library_dir,
        set(assets),
        choice_snapshot,
    )
    positions = {t.id: i for i, t in enumerate(transcript.tokens)}
    row = EditingNativePlanRecord(
        id=str(uuid4()),
        workspace_id=workspace_id,
        owner_user_id=owner_user_id,
        project_id=task.project_id,
        source_id=source.id,
        base_task_id=task.id,
        base_transcript_artifact_id=artifact.id,
        base_transcript_sha256=artifact.sha256,
        library_release=MOTION_SHA256,
        request_id=request_id,
        request_hash=fingerprint,
        origin=recipes.planning_origin,
        semantic=semantic_data,
        semantic_sha256=content_digest(semantic_data),
        recipes=recipe_data,
        recipes_sha256=content_digest(recipe_data),
        choice_snapshot=choice_snapshot,
        details={
            "source_subtitles": task.options["source_subtitles"],
            "text_status": transcript.text_status,
            "source_sha256": transcript.source_sha256,
            "audio_sha256": transcript.audio_sha256,
            "asset_snapshot": assets,
            "beats": [
                {
                    "id": beat.id,
                    "group_id": beat.group_id,
                    "relation": beat.relation,
                    "reason": beat.reason,
                    "text": "".join(
                        t.text
                        for t in transcript.tokens[
                            positions[beat.first_token_id] : positions[
                                beat.last_token_id
                            ]
                            + 1
                        ]
                    ),
                }
                for beat in semantic.beats
            ],
            "native_execution": "not_performed",
            "semantic_review": "unreviewed",
            **(
                {"planning_provenance": planning_provenance}
                if planning_provenance
                else {}
            ),
        },
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.scalar(
            select(EditingNativePlanRecord).where(
                EditingNativePlanRecord.workspace_id == workspace_id,
                EditingNativePlanRecord.owner_user_id == owner_user_id,
                EditingNativePlanRecord.request_id == request_id,
            )
        )
        if replay and replay.request_hash == fingerprint:
            return replay
        raise ApiError(
            409, "EDITING_NATIVE_PLAN_CONFLICT", "编排导入冲突，请核对已有版本。"
        ) from None
    return row


def frozen_plan_snapshot(
    row: EditingNativePlanRecord, artifact: EditingArtifactRecord
) -> dict[str, Any]:
    if (
        row.library_release != MOTION_SHA256
        or artifact.id != row.base_transcript_artifact_id
        or artifact.task_id != row.base_task_id
        or artifact.role != "transcript"
        or artifact.sha256 != row.base_transcript_sha256
        or content_digest(row.semantic) != row.semantic_sha256
        or content_digest(row.recipes) != row.recipes_sha256
        or row.origin != row.recipes.get("planning_origin")
        or row.origin not in {"operator_candidate", "tengli_gateway"}
    ):
        raise ValueError("Frozen native plan bytes/identities changed")
    return {
        "id": row.id,
        "origin": row.origin,
        "workspace_id": row.workspace_id,
        "owner_user_id": row.owner_user_id,
        "project_id": row.project_id,
        "source_id": row.source_id,
        "base_task_id": row.base_task_id,
        "base_transcript_path": str(Path(artifact.path).resolve()),
        "base_transcript_sha256": row.base_transcript_sha256,
        "semantic": row.semantic,
        "recipes": row.recipes,
        "choice_snapshot": row.choice_snapshot,
        "asset_files": row.details["asset_snapshot"],
        "source_sha256": row.details["source_sha256"],
        "audio_sha256": row.details["audio_sha256"],
        "planning_provenance": row.details.get("planning_provenance"),
    }


def admit_render_plan(
    session: Session,
    settings: Settings,
    row: EditingNativePlanRecord | None,
    source: EditingSourceRecord,
    options: EditingOptions,
) -> None:
    if not settings.video_editing_native_plan_enabled:
        raise ApiError(503, "EDITING_NATIVE_PLAN_DISABLED", "动效候选出片尚未开放。")
    if (
        not row
        or row.workspace_id != source.workspace_id
        or row.owner_user_id != source.owner_user_id
        or row.project_id != source.project_id
        or row.source_id != source.id
        or row.library_release != MOTION_SHA256
    ):
        raise ApiError(404, "EDITING_NATIVE_PLAN_NOT_FOUND", "未找到此原片的动效编排。")
    current = stored_choice_snapshot(
        session, source.workspace_id, source.owner_user_id, source.project_id
    )
    if current["sha256"] != row.choice_snapshot["sha256"]:
        raise ApiError(
            409,
            "EDITING_CHOICES_CHANGED_REPLAN_REQUIRED",
            "选组备忘已更新，请先核对并保存新的编排版本。",
        )
    if (
        options.source_subtitles != row.details["source_subtitles"]
        or options.caption_font_id != row.recipes["design"]["caption_font_id"]
        or options.language != "zh"
    ):
        raise ApiError(
            409, "EDITING_NATIVE_OPTIONS_CHANGED", "请使用该编排保存的字幕及字体设置。"
        )
