"""Owner-scoped durable semantic jobs and immutable prepared input identities."""

from datetime import UTC
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import WorkspaceContext
from .config import Settings
from .errors import ApiError
from .motion_library import MOTION_SHA256
from .video_assistance_provider import planner_configured, planner_endpoint
from .video_editing_browser_clocks import FRUIT_LIST_TEMPLATE_ID
from .video_editing_contracts import EditingPlanningTaskCreate
from .video_editing_library_choice_store import stored_choice_snapshot
from .video_editing_materials import PREFIX, material_cards, project_material_files
from .video_editing_native_plans import content_digest, source_assets
from .video_editing_overlay_templates import (
    AZL_TEMPLATE_ID,
    CXBR_TEMPLATE_ID,
    MIN_OVERLAY_TYPES,
    PRESENTER_MOTION_TEMPLATE_ID,
    motion_counts,
    overlay_template,
)
from .video_editing_story_panels import PANEL_TEMPLATE_ID
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)

FILES = {
    "request": "semantic-request.json",
    "request_evidence": "semantic-request-evidence.json",
    "response": "semantic-response.json",
    "semantic_plan": "semantic-plan.json",
    "receipt": "semantic-validated.json",
    "lineage": "input-lineage.json",
    "transcript": "transcript.json",
}


def planning_root(settings: Settings, task_id: str) -> Path:
    base = (settings.video_editing_tasks_dir / "_planning").resolve()
    root = (base / task_id).resolve()
    if not root.is_relative_to(base) or root == base:
        raise ApiError(409, "EDITING_PLAN_PATH_INVALID", "规划任务目录不匹配。")
    return root


def execution_available(settings: Settings) -> bool:
    return settings.video_editing_planning_enabled and planner_configured(settings)


def require_active_planning_template(template_id: str | None) -> None:
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
    available = (
        len(slots - excluded - runtime["unavailable_template_groups"].keys())
        if runtime is not None
        else None
    )
    return available, sorted(excluded)


def require_template_group_capacity(snapshot: dict) -> None:
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
        "error_code": row.error_code,
        "created_at": row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
        "execution_available": execution_available(settings),
        "call_state": call_state,
        "request_sha256": row.result.get("request_sha256"),
        "request_bytes": row.result.get("request_bytes"),
        "catalog_group_count": row.result.get("catalog_group_count"),
        "max_output_tokens": 5000,
        "text_status": row.result.get("text_status"),
        "semantic": semantic,
        "motion_counts": motion_counts(beat["group_id"] for beat in semantic["beats"])
        if semantic
        else None,
        "aligned_spans": row.result.get("aligned_spans", []),
        "semantic_origin": "tengli_gateway" if row.status == "completed" else None,
        "semantic_review": "unreviewed",
        "native_render_state": "preview_requested"
        if row.result.get("preview_task_id")
        else "not_compiled",
        "preview_task_id": row.result.get("preview_task_id"),
        "auto_preview": row.checkpoint.get("auto_preview", False),
        "auto_preview_available": (
            row.status == "prepared"
            and settings.video_editing_native_plan_enabled
            and bool(row.snapshot.get("overlay_template"))
        ),
        "auto_preview_error_code": (
            None
            if row.result.get("preview_task_id")
            else row.result.get("auto_preview_error_code")
        ),
        "overlay_template": row.snapshot.get("overlay_template"),
        "available_template_group_count": available,
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
    require_active_planning_template(body.template_id)
    if base.status != "completed" or base.library_release != MOTION_SHA256:
        raise ApiError(
            409,
            "EDITING_PLANNING_TRANSCRIPT_REQUIRED",
            "请先完成实际录音的识别或校对出片。",
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
            include_video_durations=body.template_id
            in {
                PRESENTER_MOTION_TEMPLATE_ID,
                AZL_TEMPLATE_ID,
                CXBR_TEMPLATE_ID,
                PANEL_TEMPLATE_ID,
            },
        ),
        "source_subtitles": base.options["source_subtitles"],
    }
    if body.template_id is not None:
        try:
            template = overlay_template(body.template_id)
        except ValueError as error:
            raise ApiError(
                422, "EDITING_TEMPLATE_INVALID", "未找到该组合模板版本。"
            ) from error
        snapshot["overlay_template"] = template
    model = settings.video_editing_plan_model
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
        require_active_planning_template(
            prepared.snapshot.get("overlay_template", {}).get("id")
        )
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
            not settings.video_editing_native_plan_enabled
            or not prepared.snapshot.get("overlay_template")
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
