"""Durable preparation/model tasks, with no provider or broker call in requests."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .config import Settings
from .errors import ApiError
from .motion_library import sha256
from .video_editing_contracts import (
    EditingNativePlanResponse,
    EditingOverlayTemplate,
    EditingPlanningPreviewBatchCreate,
    EditingPlanningPreviewBatchItem,
    EditingPlanningTaskCreate,
    EditingPlanningTaskResponse,
    EditingPreviewBase,
    EditingTaskResponse,
)
from .video_editing_hypit import hypit_runtime_blocker, requires_hypit
from .video_editing_native_plans import (
    plan_response,
    transparent_original_groups,
)
from .video_editing_overlay_templates import overlay_templates
from .video_editing_planning_preview import gateway_candidate, persist_planning_preview
from .video_editing_planning_store import (
    create_planning_task,
    execution_available,
    own_planning_task,
    planning_response,
    planning_root,
    require_active_planning_template,
)
from .video_editing_revision_preview import persist_revision_preview
from .video_editing_task_models import EditingPlanningTaskRecord
from .video_editing_task_routes import (
    dispatch as dispatch_editing,
)
from .video_editing_task_routes import (
    enabled,
    own_project,
    own_task,
)
from .video_editing_task_routes import (
    response as editing_response,
)
from .video_studio_routes import VideoWorkspace
from .video_editing_template_catalog import (
    TemplateCatalogCard,
    example_file,
    template_catalog,
)

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-editing-planning"],
)


def dispatch(request: Request, task_id: str) -> None:
    # A DB outbox scan publishes later. Tests may provide a local observer.
    observer = getattr(request.app.state, "editing_planning_dispatcher", None)
    if observer:
        observer(task_id)


@router.get("/editing-templates", response_model=list[EditingOverlayTemplate])
def list_templates(request: Request, workspace: VideoWorkspace) -> list[dict]:
    enabled(request)
    return overlay_templates()


@router.get("/editing-template-catalog", response_model=list[TemplateCatalogCard])
def list_template_catalog(request: Request, workspace: VideoWorkspace) -> list[dict]:
    return template_catalog(enabled(request), workspace.workspace_id)


@router.get("/editing-template-catalog/{template_id}/example/{kind}")
def get_template_example(
    template_id: str, kind: str, request: Request, workspace: VideoWorkspace
) -> FileResponse:
    if template_id not in {item["id"] for item in overlay_templates()}:
        raise ApiError(
            404, "EDITING_TEMPLATE_EXAMPLE_UNAVAILABLE", "此模板的示例暂不可用。"
        )
    _, path = example_file(enabled(request), template_id, kind)
    return FileResponse(
        path,
        media_type="video/mp4" if kind == "video" else "image/jpeg",
        headers={"Cache-Control": "private, no-cache"},
    )


@router.post(
    "/editing-tasks/{task_id}/planning-tasks",
    response_model=EditingPlanningTaskResponse,
)
def create_task(
    task_id: UUID,
    body: EditingPlanningTaskCreate,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    base = own_task(session, workspace, str(task_id))
    own_project(session, workspace, base.project_id)
    row = create_planning_task(session, workspace, base, body, settings)
    dispatch(request, row.id)
    return planning_response(row, settings)


@router.get(
    "/projects/{project_id}/editing-planning-tasks",
    response_model=list[EditingPlanningTaskResponse],
)
def list_tasks(
    project_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> list[dict[str, Any]]:
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    rows = session.scalars(
        select(EditingPlanningTaskRecord)
        .where(
            EditingPlanningTaskRecord.workspace_id == workspace.workspace_id,
            EditingPlanningTaskRecord.owner_user_id == workspace.principal.user_id,
            EditingPlanningTaskRecord.project_id == str(project_id),
        )
        .order_by(EditingPlanningTaskRecord.created_at.desc())
        .limit(100)
    )
    return [planning_response(row, settings) for row in rows]


@router.get(
    "/editing-planning-tasks/{task_id}", response_model=EditingPlanningTaskResponse
)
def get_task(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    return planning_response(
        own_planning_task(session, workspace, str(task_id)), enabled(request)
    )


@router.post(
    "/editing-planning-tasks/{task_id}/native-candidate",
    response_model=EditingNativePlanResponse,
)
def create_native_candidate(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    revalidate: bool = False,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    row = own_planning_task(session, workspace, str(task_id))
    own_project(session, workspace, row.project_id)
    candidate = gateway_candidate(
        session, settings, workspace, row, revalidate=revalidate
    )
    blocker = (
        hypit_runtime_blocker(settings, workspace.workspace_id)
        if requires_hypit(candidate.semantic)
        else None
    )
    return plan_response(
        candidate, settings, transparent_original_groups(settings), blocker
    )


@router.post(
    "/editing-planning-tasks/{task_id}/preview",
    response_model=EditingTaskResponse,
)
def create_preview(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    row = own_planning_task(session, workspace, str(task_id))
    own_project(session, workspace, row.project_id)
    return submit_planning_preview(row, request, workspace, session, settings)


@router.post(
    "/editing-planning-tasks/{task_id}/revision-preview",
    response_model=EditingTaskResponse,
)
def create_revision_preview(
    task_id: UUID,
    body: EditingPreviewBase,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    row = own_planning_task(session, workspace, str(task_id))
    own_project(session, workspace, row.project_id)
    task, created = persist_revision_preview(row, body, workspace, session, settings)
    if created:
        dispatch_editing(request, task.id)
    return editing_response(task, session)


@router.post(
    "/projects/{project_id}/editing-planning-preview-batch",
    response_model=list[EditingPlanningPreviewBatchItem],
)
def create_preview_batch(
    project_id: UUID,
    body: EditingPlanningPreviewBatchCreate,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> list[dict[str, Any]]:
    require_workspace_write(workspace)
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    ids = [str(task_id) for task_id in body.planning_task_ids]
    scoped_ids = set(
        session.scalars(
            select(EditingPlanningTaskRecord.id).where(
                EditingPlanningTaskRecord.id.in_(ids),
                EditingPlanningTaskRecord.workspace_id == workspace.workspace_id,
                EditingPlanningTaskRecord.owner_user_id == workspace.principal.user_id,
                EditingPlanningTaskRecord.project_id == str(project_id),
            )
        )
    )
    if scoped_ids != set(ids):
        raise ApiError(404, "EDITING_PLANNING_NOT_FOUND", "未找到本项目的规划任务。")

    # Each successful submission commits its task and planning link together.
    results = []
    for task_id in ids:
        try:
            row = own_planning_task(session, workspace, task_id)
            task = submit_planning_preview(row, request, workspace, session, settings)
            results.append({"planning_task_id": task_id, "task": task})
        except ApiError as error:
            session.rollback()
            results.append(
                {
                    "planning_task_id": task_id,
                    "error_code": error.code,
                    "error_message": error.message,
                }
            )
    return results


def submit_planning_preview(
    row: EditingPlanningTaskRecord,
    request: Request,
    workspace: WorkspaceContext,
    session: Session,
    settings: Settings,
) -> dict[str, Any]:
    task, created = persist_planning_preview(row, workspace, session, settings)
    if created:
        dispatch_editing(request, task.id)
    return editing_response(task, session)


@router.post(
    "/editing-planning-tasks/{task_id}/cancel",
    response_model=EditingPlanningTaskResponse,
)
def cancel_task(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    row = own_planning_task(session, workspace, str(task_id))
    if row.status not in {"queued", "running"}:
        raise ApiError(409, "EDITING_PLANNING_TERMINAL", "规划任务已结束。")
    values: dict[str, Any] = {
        "cancel_requested": True,
        "revision": EditingPlanningTaskRecord.revision + 1,
    }
    if row.status == "queued":
        values.update(
            status="cancelled", stage="cancelled", owner_token=None, lease_until=None
        )
    result = session.execute(
        update(EditingPlanningTaskRecord)
        .execution_options(synchronize_session=False)
        .where(
            EditingPlanningTaskRecord.id == row.id,
            EditingPlanningTaskRecord.revision == row.revision,
            EditingPlanningTaskRecord.status.in_(["queued", "running"]),
        )
        .values(**values)
    )
    if not cast(CursorResult, result).rowcount:
        raise ApiError(
            409, "EDITING_PLANNING_CHANGED", "规划状态已变化，请刷新后重试。"
        )
    session.commit()
    session.refresh(row)
    return planning_response(row, settings)


@router.post(
    "/editing-planning-tasks/{task_id}/retry",
    response_model=EditingPlanningTaskResponse,
)
def retry_task(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    row = own_planning_task(session, workspace, str(task_id))
    if row.status not in {"failed", "cancelled"}:
        raise ApiError(409, "EDITING_PLANNING_NOT_RETRYABLE", "规划任务不需要重试。")
    require_active_planning_template(row.snapshot.get("overlay_template", {}).get("id"))
    provider = planning_root(settings, row.id) / "provider"
    if row.mode == "generate" and not (provider / "semantic-response.json").is_file():
        if (provider / "semantic-submit-intent.json").exists():
            raise ApiError(
                409,
                "EDITING_PLAN_ALREADY_SUBMITTED",
                "模型结果待核对，不能自动再次提交付费请求。",
            )
        if not execution_available(settings):
            raise ApiError(503, "EDITING_PLANNING_DISABLED", "付费语义规划尚未开放。")
    result = session.execute(
        update(EditingPlanningTaskRecord)
        .execution_options(synchronize_session=False)
        .where(
            EditingPlanningTaskRecord.id == row.id,
            EditingPlanningTaskRecord.revision == row.revision,
            EditingPlanningTaskRecord.status.in_(["failed", "cancelled"]),
        )
        .values(
            status="queued",
            stage="queued",
            cancel_requested=False,
            owner_token=None,
            lease_until=None,
            error_code=None,
            checkpoint={**row.checkpoint, "dispatch_not_before": 0},
            revision=EditingPlanningTaskRecord.revision + 1,
        )
    )
    if not cast(CursorResult, result).rowcount:
        raise ApiError(
            409, "EDITING_PLANNING_CHANGED", "规划状态已变化，请刷新后重试。"
        )
    session.commit()
    session.refresh(row)
    dispatch(request, row.id)
    return planning_response(row, settings)


@router.get("/editing-planning-tasks/{task_id}/artifacts/{role}")
def get_artifact(
    task_id: UUID,
    role: str,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> FileResponse:
    settings = enabled(request)
    row = own_planning_task(session, workspace, str(task_id))
    artifact = next(
        (a for a in row.result.get("artifacts", []) if a["role"] == role), None
    )
    if not artifact:
        raise ApiError(404, "EDITING_PLANNING_ARTIFACT_NOT_FOUND", "未找到规划产物。")
    path = Path(artifact["path"]).resolve()
    if (
        not path.is_relative_to(planning_root(settings, row.id))
        or not path.is_file()
        or path.stat().st_size != artifact["bytes"]
        or artifact["bytes"] > 4_000_000
        or sha256(path) != artifact["sha256"]
    ):
        raise ApiError(
            409, "EDITING_PLANNING_ARTIFACT_CHANGED", "规划产物已变化，请恢复原文件。"
        )
    return FileResponse(
        path,
        media_type="application/json",
        filename=f"{row.id}-{role}.json",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
