"""Durable preparation/model tasks, with no provider or broker call in requests."""

from pathlib import Path
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult

from .auth import SessionDependency, require_workspace_write
from .errors import ApiError
from .motion_library import sha256
from .video_editing_contracts import (
    EditingOverlayTemplate,
    EditingPlanningTaskCreate,
    EditingPlanningTaskResponse,
)
from .video_editing_overlay_templates import overlay_templates
from .video_editing_planning_store import (
    create_planning_task,
    execution_available,
    own_planning_task,
    planning_response,
    planning_root,
)
from .video_editing_task_models import EditingPlanningTaskRecord
from .video_editing_task_routes import enabled, own_project, own_task
from .video_studio_routes import VideoWorkspace

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
