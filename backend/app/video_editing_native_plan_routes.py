"""Read saved candidate plans; ordinary clients cannot upload native recipes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from .auth import SessionDependency
from .errors import ApiError
from .video_editing_contracts import (
    EditingHighlightTarget,
    EditingImageTarget,
    EditingNativePlanResponse,
    SemanticPlan,
)
from .video_editing_highlights import highlight_targets
from .video_editing_image_edits import image_edit_targets
from .video_editing_native_plans import (
    native_edit_transcript,
    plan_response,
    transparent_original_groups,
)
from .video_editing_task_models import EditingNativePlanRecord
from .video_editing_task_routes import enabled, own_project
from .video_studio_routes import VideoWorkspace

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}",
    tags=["video-editing-native-plans"],
)


@router.get("/editing-native-plans", response_model=list[EditingNativePlanResponse])
def list_native_plans(
    project_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    include_plan_id: UUID | None = None,
) -> list[dict[str, Any]]:
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    rows = session.scalars(
        select(EditingNativePlanRecord)
        .where(
            EditingNativePlanRecord.project_id == str(project_id),
            EditingNativePlanRecord.workspace_id == workspace.workspace_id,
            EditingNativePlanRecord.owner_user_id == workspace.principal.user_id,
        )
        .order_by(EditingNativePlanRecord.created_at.desc())
        .limit(100)
    ).all()
    if include_plan_id and not any(row.id == str(include_plan_id) for row in rows):
        rows = [own_native_plan(session, workspace, project_id, include_plan_id), *rows]
    groups = transparent_original_groups(settings)
    return [plan_response(r, settings, groups) for r in rows]


@router.get(
    "/editing-native-plans/{plan_id}/highlight-options",
    response_model=list[EditingHighlightTarget],
)
def native_highlight_options(
    project_id: UUID,
    plan_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> list[EditingHighlightTarget]:
    settings = enabled(request)
    row = own_native_plan(session, workspace, project_id, plan_id)
    transcript = native_edit_transcript(session, settings, row)
    return highlight_targets(
        SemanticPlan.model_validate(row.semantic), row.recipes, transcript
    )


@router.get(
    "/editing-native-plans/{plan_id}/image-targets",
    response_model=list[EditingImageTarget],
)
def native_image_targets(
    project_id: UUID,
    plan_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> list[EditingImageTarget]:
    settings = enabled(request)
    row = own_native_plan(session, workspace, project_id, plan_id)
    transcript = native_edit_transcript(session, settings, row)
    return image_edit_targets(
        SemanticPlan.model_validate(row.semantic),
        row.recipes,
        row.details["asset_snapshot"],
        transcript,
    )


def own_native_plan(
    session: SessionDependency,
    workspace: VideoWorkspace,
    project_id: UUID,
    plan_id: UUID,
) -> EditingNativePlanRecord:
    own_project(session, workspace, str(project_id))
    row = session.get(EditingNativePlanRecord, str(plan_id))
    if (
        row is None
        or row.project_id != str(project_id)
        or row.workspace_id != workspace.workspace_id
        or row.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "EDITING_NATIVE_PLAN_NOT_FOUND", "未找到此项目的动效编排。")
    return row
