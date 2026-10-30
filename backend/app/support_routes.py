"""Customer assistance shared with the existing commerce support console."""

from typing import Annotated

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from .admin_commerce_models import SupportCaseRecord
from .auth import SessionDependency, WorkspaceDependency
from .errors import ApiError
from .models import AuditEventRecord, JobRecord, WorkspaceRecord
from .services import new_id, require_idempotency_key

router = APIRouter(tags=["support"])


class SupportCreate(BaseModel):
    issue: str = Field(min_length=3, max_length=4000)
    job_id: str | None = Field(default=None, max_length=40)


class SupportResponse(BaseModel):
    id: str
    workspace_id: str
    job_id: str | None
    issue: str
    status: str
    resolution: str

    model_config = {"from_attributes": True}


@router.get(
    "/api/v1/workspaces/{workspace_id}/support-cases",
    response_model=list[SupportResponse],
)
def list_cases(workspace: WorkspaceDependency, session: SessionDependency) -> list:
    return list(
        session.scalars(
            select(SupportCaseRecord)
            .where(
                SupportCaseRecord.workspace_id == workspace.workspace_id,
                SupportCaseRecord.created_by.is_not(None),
            )
            .order_by(SupportCaseRecord.created_at.desc())
            .limit(100)
        )
    )


@router.post(
    "/api/v1/workspaces/{workspace_id}/support-cases",
    response_model=SupportResponse,
    status_code=201,
)
def create_case(
    body: SupportCreate,
    request: Request,
    workspace: WorkspaceDependency,
    session: SessionDependency,
    key: Annotated[str, Header(alias="Idempotency-Key")],
) -> SupportCaseRecord:
    request_key = require_idempotency_key(key)
    issue = body.issue.strip()
    if len(issue) < 3:
        raise ApiError(422, "SUPPORT_ISSUE_REQUIRED", "请描述遇到的问题。")
    if body.job_id:
        job = session.scalar(
            select(JobRecord).where(
                JobRecord.id == body.job_id,
                JobRecord.workspace_id == workspace.workspace_id,
            )
        )
        if job is None:
            raise ApiError(404, "SUPPORT_JOB_NOT_FOUND", "未找到当前工作区的关联任务。")
    session.execute(
        select(WorkspaceRecord.id)
        .where(WorkspaceRecord.id == workspace.workspace_id)
        .with_for_update()
    ).scalar_one()
    existing = session.scalar(
        select(SupportCaseRecord).where(
            SupportCaseRecord.workspace_id == workspace.workspace_id,
            SupportCaseRecord.request_key == request_key,
        )
    )
    if existing:
        if existing.issue != issue or existing.job_id != body.job_id:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "此请求编号已用于其他问题。")
        return existing
    row = SupportCaseRecord(
        id=new_id("sup"),
        workspace_id=workspace.workspace_id,
        created_by=workspace.principal.user_id,
        actor_user_id=workspace.principal.user_id,
        job_id=body.job_id,
        request_key=request_key,
        issue=issue,
        status="open",
        resolution="",
    )
    session.add(row)
    session.add(
        AuditEventRecord(
            workspace_id=workspace.workspace_id,
            actor_user_id=workspace.principal.user_id,
            action="support.created",
            resource_type="support_case",
            resource_id=row.id,
            request_id=getattr(request.state, "request_id", None),
            details={"job_id": row.job_id},
        )
    )
    session.commit()
    return row
