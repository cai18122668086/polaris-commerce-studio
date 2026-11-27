"""Owner-scoped durable semantic jobs and immutable prepared input identities."""

from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import video_credit_billing as video_credits
from .auth import WorkspaceContext
from .bihuo_suite.registry import ENGINE as BIHUO_ENGINE
from .bihuo_suite.registry import definition as bihuo_definition
from .bihuo_suite.registry import is_template as bihuo_template
from .config import Settings
from .errors import ApiError
from .motion_library import MOTION_SHA256
from .video_assistance_provider import planner_configured, planner_endpoint
from .video_editing_apple_pipeline import (
    ENGINE as APPLE_ENGINE,
)
from .video_editing_apple_pipeline import (
    TEMPLATE_ID as APPLE_TEMPLATE_ID,
)
from .video_editing_apple_pipeline import (
    TEMPLATE_NAME as APPLE_TEMPLATE_NAME,
)
from .video_editing_apple_pipeline import (
    suite_bundle,
    suite_engine,
)
from .video_editing_browser_clocks import FRUIT_LIST_TEMPLATE_ID
from .video_editing_contracts import EditingPlanningTaskCreate
from .video_editing_library_choice_store import stored_choice_snapshot
from .video_editing_materials import PREFIX, material_cards, project_material_files
from .video_editing_native_plans import content_digest, source_assets
from .video_editing_overlay_templates import (
    MIN_OVERLAY_TYPES,
    motion_counts,
    overlay_template,
)
from .video_editing_planning_quality import require_reference_transcript
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_editing_template_capabilities import suite_template_blocker
from .video_editing_template_styles import style_blockers
from .video_editing_transcript_store import (
    read_transcript_artifact,
    recorded_source_frame,
    require_native_source_frame,
)
from .video_planner_policy import EMPTY_RESPONSE, saved_response_empty

FILES = {
    "tutorial_plan": "tutorial-plan.json",
    "suite_plan": "suite-plan.json",
    "request": "semantic-request.json",
    "request_evidence": "semantic-request-evidence.json",
    "response": "semantic-response.json",
    "semantic_plan": "semantic-plan.json",
    "receipt": "semantic-validated.json",
    "lineage": "input-lineage.json",
    "transcript": "transcript.json",
    "material_placement": "material-placement.json",
}


def planning_root(settings: Settings, task_id: str) -> Path:
    base = (settings.video_editing_tasks_dir / "_planning").resolve()
    root = (base / task_id).resolve()
    if not root.is_relative_to(base) or root == base:
        raise ApiError(409, "EDITING_PLAN_PATH_INVALID", "规划任务目录不匹配。")
    return root


def execution_available(settings: Settings) -> bool:
    return settings.video_editing_planning_enabled and planner_configured(settings)


def require_active_planning_template(
    template_id: str | None, settings: Settings | None = None
) -> None:
    if settings is not None:
        # Fail before the paid planning call, not at render after paying.
        blocker = suite_template_blocker(template_id, settings)
        if blocker:
            raise ApiError(409, "EDITING_TEMPLATE_CAPABILITY_UNAVAILABLE", blocker)
    if bihuo_template(template_id):
        from .bihuo_suite.registry import available

        assert template_id is not None
        if not available(template_id):
            raise ApiError(
                409, "EDITING_TEMPLATE_INSTALLING", "此模板正在更新，请稍后重试。"
            )
    if template_id == FRUIT_LIST_TEMPLATE_ID:
        raise ApiError(
            409,
            "EDITING_TEMPLATE_RETIRED",
            "该模板已从网站剪辑下架，请选择其他组合模板。",
        )


def own_planning_task(
    session: Session, workspace: WorkspaceContext, task_id: str
) -> EditingPlanningTaskRecord:
    row = session.get(EditingPlanningTaskRecord, task_id)
    if (
        not row
        or row.workspace_id != workspace.workspace_id
        or row.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "EDITING_PLANNING_NOT_FOUND", "未找到语义规划任务。")
    return row


def _template_availability(snapshot: dict) -> tuple[int | None, list[str]]:
    template = snapshot.get("overlay_template")
    if not template:
        return None, []
    slots = {slot["group_id"] for slot in template["slots"]} - {"Z-M00"}
    excluded = {
        note["target_id"]
        for note in snapshot["choice_snapshot"]["notes"]
        if note["target_kind"] == "group" and note["choice"] == "avoid"
    } & slots
    runtime = snapshot.get("planning_runtime")
    if runtime and runtime.get("template_style", {}).get("allowed_group_ids"):
        slots &= set(runtime["template_style"]["allowed_group_ids"])
        excluded &= slots
    available = (
        len(slots - excluded - runtime["unavailable_template_groups"].keys())
        if runtime is not None
        else None
    )
    return available, sorted(excluded)


def require_template_group_capacity(snapshot: dict) -> None:
    blockers = style_blockers(snapshot)
    if blockers:
        raise ApiError(409, "EDITING_TEMPLATE_STYLE_UNAVAILABLE", blockers[0])
    available, _ = _template_availability(snapshot)
    if available is not None and available < MIN_OVERLAY_TYPES:
        raise ApiError(
            409,
            "EDITING_TEMPLATE_GROUPS_INSUFFICIENT",
            f"本次仅有 {available} 种可选动效，"
            f"成片至少需要 {MIN_OVERLAY_TYPES} 种。"
            "请核对避用备忘、素材或模板后重新准备。",
        )


def planning_response(
    row: EditingPlanningTaskRecord, settings: Settings
) -> dict[str, Any]:
    provider = planning_root(settings, row.id) / "provider"
    call_state = (
        "response_saved"
        if (provider / FILES["response"]).is_file()
        else "intent_saved"
        if (provider / "semantic-submit-intent.json").is_file()
        else "not_submitted"
    )
    available, excluded = _template_availability(row.snapshot)
    semantic = row.result.get("semantic")
    return {
        **(
            {
                "engine": row.snapshot.get("engine", APPLE_ENGINE),
                "template_id": row.snapshot.get("template_id", APPLE_TEMPLATE_ID),
                "template_name": row.snapshot.get("template_name", APPLE_TEMPLATE_NAME),
                "suite_plan": row.result.get("suite_plan"),
            }
            if suite_engine(row.snapshot)
            else {}
        ),
        "id": row.id,
        "project_id": row.project_id,
        "source_id": row.source_id,
        "base_task_id": row.base_task_id,
        "base_transcript_artifact_id": row.base_transcript_artifact_id,
        "base_transcript_sha256": row.base_transcript_sha256,
        "library_release": row.library_release,
        "choice_snapshot_sha256": row.snapshot["choice_snapshot"]["sha256"],
        "prepared_task_id": row.prepared_task_id,
        "mode": row.mode,
        "model": row.model,
        "gateway_host": (row.snapshot.get("gateway") or {}).get("host"),
        "status": row.status,
        "stage": row.stage,
        "revision": row.revision,
        "attempts": row.attempts,
        "cancel_requested": row.cancel_requested,
        "error_code": EMPTY_RESPONSE
        if row.status == "failed" and saved_response_empty(provider)
        else row.error_code,
        "created_at": row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
        "execution_available": execution_available(settings),
        "call_state": call_state,
        "request_sha256": row.result.get("request_sha256"),
        "request_bytes": row.result.get("request_bytes"),
        "catalog_group_count": row.result.get("catalog_group_count"),
        "max_output_tokens": row.result.get("max_output_tokens", 5000),
        "text_status": row.result.get("text_status"),
        "semantic": semantic,
        "motion_counts": motion_counts(beat["group_id"] for beat in semantic["beats"])
        if semantic
        else None,
        "aligned_spans": row.result.get("aligned_spans", []),
        "semantic_origin": "tengli_gateway" if row.status == "completed" else None,
        "semantic_review": "unreviewed",
        "semantic_adaptation": row.result.get("semantic_adaptation"),
        "native_render_state": "preview_requested"
        if row.result.get("preview_task_id")
        else "not_compiled",
        "preview_task_id": row.result.get("preview_task_id"),
        "auto_preview": row.checkpoint.get("auto_preview", False),
        "auto_preview_available": (
            row.status == "prepared"
            and (
                suite_engine(row.snapshot)
                or (
                    settings.video_editing_native_plan_enabled
                    and bool(row.snapshot.get("overlay_template"))
                )
            )
        ),
        "auto_preview_error_code": (
            None
            if row.result.get("preview_task_id")
            else row.result.get("auto_preview_error_code")
        ),
        "overlay_template": row.snapshot.get("overlay_template"),
        "available_template_group_count": available,
        "template_style_blockers": style_blockers(row.snapshot) or None,
        "excluded_template_group_ids": excluded or None,
        "unavailable_template_group_ids": sorted(
            row.snapshot["planning_runtime"]["unavailable_template_groups"]
        )
        if "planning_runtime" in row.snapshot
        else None,
        "project_image_requirements": row.snapshot.get("planning_runtime", {}).get(
            "project_image_requirements"
        ),
        "artifacts": [
            {
                "id": row.id + ":" + a["role"],
                "role": a["role"],
                "mime": "application/json",
                "sha256": a["sha256"],
                "bytes": a["bytes"],
                "duration_ms": None,
                "url": (
                    f"/api/v1/video-studio/workspaces/{row.workspace_id}"
                    f"/editing-planning-tasks/{row.id}/artifacts/{a['role']}"
                ),
            }
            for a in row.result.get("artifacts", [])
        ],
    }


def hold_planning(
    session: Session, settings: Settings, row: EditingPlanningTaskRecord
) -> None:
    """Hold the paid model call and, for auto preview, the preview render."""
    if row.mode != "generate":
        return
    video_credits.hold(
        session,
        settings,
        row.workspace_id,
        "editing_planning",
        "video_planning",
        row.id,
    )
    # Column defaults are applied on insert; a new row still has None here.
    checkpoint, result = row.checkpoint or {}, row.result or {}
    if checkpoint.get("auto_preview") and not result.get("preview_task_id"):
        video_credits.hold(
            session,
            settings,
            row.workspace_id,
            "editing_render",
            "video_planning",
            row.id,
        )


def create_planning_task(
    session: Session,
    workspace: WorkspaceContext,
    base: EditingTaskRecord,
    body: EditingPlanningTaskCreate,
    settings: Settings,
) -> EditingPlanningTaskRecord:
    fingerprint = content_digest(
        {
            "base_task_id": base.id,
            **body.model_dump(mode="json"),
            "library_release": MOTION_SHA256,
        }
    )
    scope = (
        EditingPlanningTaskRecord.workspace_id == workspace.workspace_id,
        EditingPlanningTaskRecord.owner_user_id == workspace.principal.user_id,
    )
    previous = session.scalar(
        select(EditingPlanningTaskRecord).where(
            *scope, EditingPlanningTaskRecord.request_id == str(body.request_id)
        )
    )
    if previous:
        if previous.request_hash != fingerprint:
            raise ApiError(
                409, "EDITING_PLANNING_REQUEST_REUSED", "此请求编号已用于其他规划输入。"
            )
        return previous
    require_active_planning_template(body.template_id, settings)
    if base.status != "completed" or base.library_release != MOTION_SHA256:
        raise ApiError(
            409,
            "EDITING_PLANNING_TRANSCRIPT_REQUIRED",
            "请先完成实际口播的识别或校对对齐。",
        )
    source = session.get(EditingSourceRecord, base.source_id)
    if (
        not source
        or source.workspace_id != workspace.workspace_id
        or source.owner_user_id != workspace.principal.user_id
        or source.project_id != base.project_id
    ):
        raise ApiError(404, "EDITING_SOURCE_NOT_FOUND", "未找到对应原片。")
    artifact = session.scalar(
        select(EditingArtifactRecord).where(
            EditingArtifactRecord.task_id == base.id,
            EditingArtifactRecord.role == "transcript",
        )
    )
    if not artifact:
        raise ApiError(
            409, "EDITING_PLANNING_TRANSCRIPT_REQUIRED", "原任务缺少实际转录产物。"
        )
    require_native_source_frame(recorded_source_frame(artifact))
    choices = stored_choice_snapshot(
        session, workspace.workspace_id, workspace.principal.user_id, base.project_id
    )
    selected = project_material_files(
        session,
        settings,
        source,
        {PREFIX + str(key) for key in body.material_ids or []},
    )
    snapshot: dict[str, Any] = {
        "gateway": planner_endpoint(settings),
        "public_copy_only": True,
        "source_sha256": source.media_sha256,
        "choice_snapshot": choices,
        "asset_cards": material_cards(
            source_assets(source) | selected,
            include_video_durations=True,
        ),
        "source_subtitles": base.options["source_subtitles"],
        **({"music": body.music} if body.music is not None else {}),
        # W4: frozen only when chosen, so older snapshots stay byte-identical.
        **(
            {"supplement": body.supplement.model_dump(mode="json")}
            if body.supplement is not None and body.supplement.mg is not None
            else {}
        ),
    }
    if body.template_id == APPLE_TEMPLATE_ID or bihuo_template(body.template_id):
        if base.options["source_subtitles"] != "none":
            raise ApiError(
                422,
                "EDITING_APPLE_CLEAN_SOURCE_REQUIRED",
                "此模板需要没有烧字字幕的口播视频。",
            )
        snapshot.update(
            engine=APPLE_ENGINE
            if body.template_id == APPLE_TEMPLATE_ID
            else BIHUO_ENGINE,
            engine_bundle=suite_bundle(settings)
            if body.template_id == APPLE_TEMPLATE_ID
            else suite_bundle(settings, body.template_id),
            creative_options=body.creative_options.model_dump(mode="json")
            if body.creative_options
            else {},
        )
        if body.template_id != APPLE_TEMPLATE_ID:
            assert body.template_id is not None
            from .bihuo_suite.registry import creative_options as suite_creative_options

            snapshot["creative_options"] = suite_creative_options(
                body.template_id, snapshot["creative_options"]
            )
            snapshot.update(
                template_id=body.template_id,
                template_name=bihuo_definition(body.template_id)["name"],
            )
        snapshot["asset_cards"] = material_cards(
            source_assets(source) | selected, include_video_durations=True
        )
    elif body.template_id is not None:
        try:
            template = overlay_template(body.template_id)
        except ValueError as error:
            raise ApiError(
                422, "EDITING_TEMPLATE_INVALID", "未找到该组合模板版本。"
            ) from error
        snapshot["overlay_template"] = template
    model = settings.video_editing_plan_model
    if body.mode == "prepare":
        from .video_editing_editorial_suite import ENGINE as EDITORIAL_ENGINE
        from .video_editing_editorial_suite import bundle as editorial_bundle
        from .video_editing_editorial_suite import use_editorial
        from .video_editing_template_styles import STYLES
        from .video_editing_tutorial_plan import content_context, optional_plan

        template_id = body.template_id
        if template_id and use_editorial(template_id, selected):
            snapshot.pop("overlay_template", None)
            snapshot.update(
                engine=EDITORIAL_ENGINE,
                template_id=template_id,
                template_name=STYLES[template_id]["name"],
                engine_bundle=editorial_bundle(template_id, suite_bundle(settings)),
                creative_options={},
            )
        # Selected recordings have one owner: the source tutorial timeline.
        # Native picture slots retain the caller's chosen still images.
        cards = snapshot["asset_cards"]
        snapshot["material_layout_version"] = 1
        if any(card["kind"] == "video" for card in cards):
            tutorial_transcript = read_transcript_artifact(
                artifact, base, settings.video_editing_tasks_dir
            )
            tutorial = content_context(source.id, tutorial_transcript, cards)
            assert tutorial is not None
            snapshot["tutorial_context"] = tutorial
            snapshot["adaptive_tutorial_playback"] = True
            snapshot["tutorial_shared_plan"] = optional_plan(
                settings.video_editing_tasks_dir, tutorial, tutorial_transcript
            )
            snapshot["asset_cards"] = [
                card for card in cards if card["kind"] != "video"
            ]
    if body.mode == "generate":
        prepared = own_planning_task(session, workspace, str(body.prepared_task_id))
        if (
            prepared.mode != "prepare"
            or prepared.status != "prepared"
            or prepared.base_task_id != base.id
            or prepared.source_id != source.id
            or prepared.project_id != base.project_id
            or prepared.base_transcript_artifact_id != artifact.id
            or prepared.base_transcript_sha256 != artifact.sha256
        ):
            raise ApiError(
                409,
                "EDITING_PREPARED_REQUEST_INVALID",
                "准备记录与当前原片或转录不匹配。",
            )
        existing = session.scalar(
            select(EditingPlanningTaskRecord).where(
                *scope, EditingPlanningTaskRecord.prepared_task_id == prepared.id
            )
        )
        if existing:
            return existing
        # The same request (same speech, template, materials and settings gives
        # the same request hash) already has a live or finished paid planning in
        # this project. A refreshed page or a second check must join that result
        # instead of paying again; a failed run may still be retried, and the
        # user may confirm a deliberate re-plan (replan=true, charged again).
        duplicate = session.scalar(
            select(EditingPlanningTaskRecord.id)
            .where(
                *scope,
                EditingPlanningTaskRecord.project_id == base.project_id,
                EditingPlanningTaskRecord.mode == "generate",
                EditingPlanningTaskRecord.status.in_(
                    ("queued", "running", "completed")
                ),
                EditingPlanningTaskRecord.snapshot[
                    "expected_request_sha256"
                ].as_string()
                == prepared.result.get("request_sha256"),
            )
            .limit(1)
        )
        if duplicate and prepared.result.get("request_sha256") and not body.replan:
            raise ApiError(
                409,
                "EDITING_PLAN_ALREADY_GENERATED",
                "这条口播已用同样的模板和素材剪过，请在结果区确认或下载，不会重复扣费。",
            )
        require_active_planning_template(
            prepared.snapshot.get("overlay_template", {}).get("id")
        )
        require_active_planning_template(prepared.snapshot.get("template_id"), settings)
        if not execution_available(settings):
            raise ApiError(
                503,
                "EDITING_PLANNING_DISABLED",
                "付费语义规划尚未开放；可先准备完整请求。",
            )
        if prepared.snapshot.get("gateway") != snapshot["gateway"]:
            raise ApiError(
                409,
                "EDITING_PLAN_ENDPOINT_CHANGED",
                "规划网关已变化，请重新准备后核对。",
            )
        if (
            prepared.snapshot["choice_snapshot"]["sha256"] != choices["sha256"]
            or prepared.model != model
        ):
            raise ApiError(
                409,
                "EDITING_CHOICES_CHANGED_REPLAN_REQUIRED",
                "选组或模型已变化，请重新准备请求后核对。",
            )
        require_template_group_capacity(prepared.snapshot)
        if body.auto_preview and (
            (
                not settings.video_editing_native_plan_enabled
                and not suite_engine(prepared.snapshot)
            )
            or not (
                prepared.snapshot.get("overlay_template")
                or suite_engine(prepared.snapshot)
            )
        ):
            raise ApiError(
                409,
                "EDITING_AUTO_PREVIEW_UNAVAILABLE",
                "自动生成代理需要可运行的组合模板。请重新准备或单独提交语义规划。",
            )
        snapshot = {
            **prepared.snapshot,
            "expected_request_sha256": prepared.result["request_sha256"],
            "prepared_artifacts": prepared.result["artifacts"],
        }
    if (
        source.kind == "generation_task"
        and (source.details.get("generation_lineage") or {}).get(
            "generation_script_snapshot"
        )
        == "matched"
    ):
        require_reference_transcript(
            read_transcript_artifact(artifact, base, settings.video_editing_tasks_dir),
            source.kind,
            source.details["generation_lineage"],
        )
    row = EditingPlanningTaskRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=base.project_id,
        source_id=source.id,
        base_task_id=base.id,
        base_transcript_artifact_id=artifact.id,
        base_transcript_sha256=artifact.sha256,
        prepared_task_id=str(body.prepared_task_id) if body.prepared_task_id else None,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        library_release=MOTION_SHA256,
        mode=body.mode,
        model=model,
        snapshot=snapshot,
        checkpoint={"auto_preview": True} if body.auto_preview else {},
    )
    session.add(row)
    try:
        hold_planning(session, settings, row)
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.scalar(
            select(EditingPlanningTaskRecord).where(
                *scope, EditingPlanningTaskRecord.request_id == str(body.request_id)
            )
        )
        if replay and replay.request_hash == fingerprint:
            return replay
        if body.prepared_task_id:
            replay = session.scalar(
                select(EditingPlanningTaskRecord).where(
                    *scope,
                    EditingPlanningTaskRecord.prepared_task_id
                    == str(body.prepared_task_id),
                )
            )
            if replay:
                return replay
        raise ApiError(
            409, "EDITING_PLANNING_CONFLICT", "规划请求发生冲突，请刷新后重试。"
        ) from None
    return row
