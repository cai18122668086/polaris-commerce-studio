"""Read saved candidate plans; ordinary clients cannot upload native recipes."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from .auth import SessionDependency
from .video_editing_contracts import EditingNativePlanResponse
from .video_editing_native_plans import plan_response
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
    )
    return [plan_response(r, settings) for r in rows]
