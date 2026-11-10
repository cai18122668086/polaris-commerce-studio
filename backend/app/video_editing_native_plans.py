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
from .motion_library import MOTION_SHA256, read_json
from .video_editing_contracts import EditingOptions, SemanticPlan, Transcript
from .video_editing_effect_edits import apply_effect_edits
from .video_editing_episode_compiler import EpisodeRecipeBundle
from .video_editing_highlights import apply_highlight_edits, editable_highlight_roles
from .video_editing_hypit import (
    HYPIT_BLOCKER_MESSAGES,
    hypit_runtime_blocker,
    requires_hypit,
)
from .video_editing_hypit_chart import FLOW_CHART_DESIGN, FLOW_CHART_TEMPLATE_ID
from .video_editing_hypit_strips import FLOW_GROUP
from .video_editing_image_edits import (
    apply_image_edits,
    editable_image_roles,
    resolve_image_edits,
)
from .video_editing_library_choice_store import stored_choice_snapshot
from .video_editing_materials import project_material_files, verify_material_cards
from .video_editing_native_sound import music_replacement_options
from .video_editing_overlay_templates import (
    MIN_OVERLAY_TYPES,
    motion_counts,
    overlay_template,
    validate_template_plan,
)
from .video_editing_planner import validate_plan
from .video_editing_render_edits import (
    available_render_edits,
    continuous_overlay_groups,
    validate_render_edits,
)
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingNativePlanRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_editing_transcript_store import (
    read_transcript_artifact,
    recorded_source_frame,
    require_native_source_frame,
)
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


def transparent_original_groups(settings: Settings) -> set[str]:
    return {
        group["id"]
        for group in read_json(
            settings.video_editing_library_dir / "catalog/groups.json"
        )["groups"]
        if group.get("kind") == "subtitle" and group.get("backend") == "subtitle"
    }


FLOW_CHART_WARNING = "HY-A7 的饼图需先绑定本期经核对的数据，当前只开放原生组件验证。"


def requires_flow_chart(semantic: dict, recipes: dict) -> bool:
    entries = recipes.get("entries", {})
    return any(
        beat["group_id"] == FLOW_GROUP
        and (
            recipes.get("overlay_template_id") != FLOW_CHART_TEMPLATE_ID
            or entries.get(beat["id"], {}).get("recipe", {}).get("design_id")
            != FLOW_CHART_DESIGN
        )
        for beat in semantic["beats"]
    )


def original_scene_groups(settings: Settings) -> set[str]:
    catalog = read_json(settings.video_editing_library_dir / "catalog/groups.json")
    return {group["id"] for group in catalog["groups"] if group.get("kind") == "visual"}


def _saved_template(template_id: str | None) -> dict | None:
    if template_id:
        try:
            return overlay_template(template_id)
        except ValueError:
            pass
    return None


def plan_response(
    row: EditingNativePlanRecord,
    settings: Settings,
    transparent_groups: set[str],
    hypit_blocker: str | None,
) -> dict[str, Any]:
    editable, has_music = available_render_edits(
        row.semantic, row.recipes, row.choice_snapshot
    )
    needs_chart = requires_flow_chart(row.semantic, row.recipes)
    warnings = row.semantic.get("warnings", [])
    needs_hypit = requires_hypit(row.semantic)
    if needs_hypit and hypit_blocker:
        warnings = [*warnings, HYPIT_BLOCKER_MESSAGES[hypit_blocker]]
    if needs_chart:
        warnings = [*warnings, FLOW_CHART_WARNING]
    template_id = row.recipes.get("overlay_template_id")
    template = _saved_template(template_id)
    template_unavailable = bool(template_id and template is None)
    if template_unavailable:
        warnings = [*warnings, f"原编排使用的模板 {template_id} 在当前版本不可用。"]
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
        "beats": [
            {
                **detail,
                "id": beat["id"],
                "source_only_available": beat["id"] in editable,
                **(
                    {"question_gloss": beat["question_gloss"]}
                    if beat.get("question_gloss")
                    else {}
                ),
            }
            for beat, detail in zip(
                row.semantic["beats"], row.details["beats"], strict=True
            )
        ],
        "warnings": warnings,
        "missing_materials": row.semantic.get("missing_materials", []),
        "text_status": row.details["text_status"],
        "source_subtitles": row.details["source_subtitles"],
        "caption_font_id": row.recipes["design"]["caption_font_id"],
        "choice_snapshot_sha256": row.choice_snapshot["sha256"],
        "semantic_review": "unreviewed",
        "music_edit_available": has_music,
        "image_edit_available": any(
            editable_image_roles(beat, row.recipes) for beat in row.semantic["beats"]
        ),
        "highlight_edit_available": any(
            editable_highlight_roles(beat, row.recipes)
            for beat in row.semantic["beats"]
        ),
        "continuous_preview_available": len(
            continuous_overlay_groups(
                row.semantic,
                row.recipes,
                transparent_groups,
                allow_hypit_insets=row.details["source_subtitles"] == "none"
                and needs_hypit
                and hypit_blocker is None,
                allow_question_insets=row.details["source_subtitles"] == "none",
                scene_groups=original_scene_groups(settings)
                if row.details["source_subtitles"] == "none"
                else None,
            )
        )
        >= MIN_OVERLAY_TYPES,
        "overlay_template": template,
        "render_available": settings.video_editing_native_plan_enabled
        and not template_unavailable
        and not needs_chart
        and (not needs_hypit or hypit_blocker is None),
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
    recipes: EpisodeRecipeBundle | None = None,
) -> EditingNativePlanRecord:
    """Adopt a captured server result with a trusted or generated recipe."""
    from .video_editing_planning_provenance import verify_gateway_planning

    verified = verify_gateway_planning(
        session, settings, workspace_id, owner_user_id, planning_task_id
    )
    template = verified.task.snapshot.get("overlay_template")
    if template is not None and (
        motion_counts(beat.group_id for beat in verified.semantic.beats)[
            "distinct_groups"
        ]
        < MIN_OVERLAY_TYPES
    ):
        raise ApiError(
            422,
            "EDITING_PLAN_GROUPS_INSUFFICIENT",
            f"候选少于 {MIN_OVERLAY_TYPES} 种不同原生动效，暂不能生成代理。",
        )
    if recipes is None:
        from .video_editing_overlay_recipes import build_overlay_recipes

        if template is None:
            raise ApiError(
                422, "EDITING_TEMPLATE_REQUIRED", "此规划需要先选择组合模板。"
            )
        recipes = build_overlay_recipes(
            settings.video_editing_library_dir,
            verified.semantic,
            verified.transcript,
            verified.task.base_transcript_sha256,
            template,
            verified.task.snapshot["choice_snapshot"],
            verified.task.snapshot["asset_cards"],
        )
    if recipes.planning_origin != "tengli_gateway":
        raise ApiError(
            422, "EDITING_PLANNER_PROVENANCE_REQUIRED", "配方来源需与已捕获规划一致。"
        )
    if recipes.overlay_template_id != (template or {}).get("id"):
        raise ApiError(
            422, "EDITING_TEMPLATE_CHANGED", "原生编排必须沿用已准备的组合模板版本。"
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
    if recipes.overlay_template_id:
        validate_template_plan(
            semantic, overlay_template(recipes.overlay_template_id), complete=True
        )
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
    require_native_source_frame(recorded_source_frame(artifact))
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
    if (
        planning_provenance
        and choice_snapshot["sha256"] != planning_provenance["choice_snapshot_sha256"]
    ):
        raise ApiError(
            409,
            "EDITING_CHOICES_CHANGED_REPLAN_REQUIRED",
            "选组已变化，请重新准备并核对规划。",
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


def native_edit_transcript(
    session: Session, settings: Settings, row: EditingNativePlanRecord
) -> Transcript:
    task = session.get(EditingTaskRecord, row.base_task_id)
    artifact = session.get(EditingArtifactRecord, row.base_transcript_artifact_id)
    if (
        not task
        or not artifact
        or (task.project_id, task.workspace_id, task.owner_user_id, task.source_id)
        != (row.project_id, row.workspace_id, row.owner_user_id, row.source_id)
    ):
        raise ApiError(409, "EDITING_PLAN_SOURCE_CHANGED", "编排的原转录暂不可用。")
    try:
        frozen_plan_snapshot(row, artifact)
    except ValueError as error:
        raise ApiError(
            409, "EDITING_PLAN_SOURCE_CHANGED", "编排的原转录已变化。"
        ) from error
    transcript = read_transcript_artifact(
        artifact, task, settings.video_editing_tasks_dir
    )
    if transcript.source_sha256 != row.details["source_sha256"]:
        raise ApiError(409, "EDITING_PLAN_SOURCE_CHANGED", "编排的原片与转录不匹配。")
    return transcript


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
    if requires_flow_chart(row.semantic, row.recipes):
        raise ApiError(409, "EDITING_HYPIT_FLOW_CHART_REQUIRED", FLOW_CHART_WARNING)
    template_id = row.recipes.get("overlay_template_id")
    if template_id and _saved_template(template_id) is None:
        raise ApiError(
            409, "EDITING_TEMPLATE_CHANGED", "原编排使用的模板在当前版本不可用。"
        )
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
    if options.native_edits:
        try:
            validate_render_edits(
                options.native_edits, row.semantic, row.recipes, current
            )
        except ValueError as error:
            raise ApiError(
                422,
                "EDITING_NATIVE_EDITS_INVALID",
                "所选段落或背景音乐不适用于这份编排。",
            ) from error
    edits = options.native_edits
    if edits and (
        edits.music_track_id
        or edits.highlight_edits
        or edits.image_edits
        or edits.effect_edits
    ):
        transcript = native_edit_transcript(session, settings, row)
    if edits and edits.music_track_id:
        try:
            replacements = music_replacement_options(
                settings.video_editing_library_dir,
                row.recipes.get("sound"),
                transcript,
                current,
                edits.music_track_id,
            )
            if replacements is None or not replacements.choices:
                raise ValueError("Background music replacement is unavailable")
        except (ValueError, KeyError, OSError) as error:
            raise ApiError(
                422,
                "EDITING_MUSIC_UNAVAILABLE",
                "请选择符合本期时长、选材备忘及原件校验的原库背景音乐。",
            ) from error
    if edits and (edits.highlight_edits or edits.image_edits or edits.effect_edits):
        semantic = SemanticPlan.model_validate(row.semantic)
        assets = row.details["asset_snapshot"]
    if edits and edits.highlight_edits:
        try:
            edited, _ = apply_highlight_edits(
                edits.highlight_edits,
                semantic,
                row.recipes,
                transcript,
            )
            validate_plan(
                edited,
                transcript,
                settings.video_editing_library_dir,
                set(assets),
                current,
            )
            semantic = edited
        except ValueError as error:
            raise ApiError(
                422,
                "EDITING_HIGHLIGHT_INVALID",
                "请从这份编排列出的实录短语中重新选择。",
            ) from error
    if edits and edits.image_edits:
        assets = resolve_image_edits(
            session, settings, source, edits.image_edits, assets
        )
        try:
            edited, _ = apply_image_edits(
                edits.image_edits, semantic, row.recipes, assets, transcript
            )
            validate_plan(
                edited,
                transcript,
                settings.video_editing_library_dir,
                set(assets),
                current,
            )
            semantic = edited
        except (ValueError, KeyError) as error:
            raise ApiError(
                422,
                "EDITING_IMAGE_EDIT_INVALID",
                "请选择不同的本期图片，透明图槽需使用含透明像素的图片。",
            ) from error
    effective_semantic, effective_recipes = row.semantic, row.recipes
    if edits and edits.effect_edits:
        try:
            semantic, revised, _ = apply_effect_edits(
                settings.video_editing_library_dir,
                edits.effect_edits,
                semantic,
                EpisodeRecipeBundle.model_validate(row.recipes),
                transcript,
                current,
                set(assets),
            )
        except ValueError as error:
            raise ApiError(
                422,
                "EDITING_EFFECT_EDIT_INVALID",
                "请选择该实录段可用的同模板原生动效。",
            ) from error
        effective_semantic = semantic.model_dump(mode="json")
        effective_recipes = revised.model_dump(mode="json")
    excluded = set(edits.source_only_beat_ids) if edits else None
    needs_hypit = requires_hypit(effective_semantic, excluded)
    if needs_hypit and (
        blocker := hypit_runtime_blocker(settings, source.workspace_id)
    ):
        raise ApiError(503, blocker, HYPIT_BLOCKER_MESSAGES[blocker])
    if (
        options.delivery == "preview_first"
        and len(
            continuous_overlay_groups(
                effective_semantic,
                effective_recipes,
                transparent_original_groups(settings),
                excluded,
                allow_hypit_insets=options.source_subtitles == "none" and needs_hypit,
                allow_question_insets=options.source_subtitles == "none",
                scene_groups=original_scene_groups(settings)
                if options.source_subtitles == "none"
                else None,
            )
        )
        < MIN_OVERLAY_TYPES
    ):
        raise ApiError(
            422,
            "EDITING_CONTINUOUS_COMBINATION_REQUIRED",
            "连续口播预览需要保留至少五种不同的原生动效。",
        )
