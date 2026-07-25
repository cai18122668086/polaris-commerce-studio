from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_session
from .domain import (
    MembershipRole,
    MembershipStatus,
    UserStatus,
    WorkspaceStatus,
)
from .errors import ApiError
from .models import (
    UserRecord,
    WorkspaceCreditAccountRecord,
    WorkspaceLimitRecord,
    WorkspaceMemberRecord,
    WorkspaceRecord,
)


@dataclass(frozen=True)
class Principal:
    user_id: str


@dataclass(frozen=True)
class WorkspaceContext:
    principal: Principal
    workspace_id: str
    role: MembershipRole


SessionDependency = Annotated[Session, Depends(get_session)]


def ensure_development_identity(request: Any) -> None:
    application = getattr(request, "app", request)
    settings = application.state.settings
    if settings.auth_mode != "development":
        return
    session_factory = application.state.session_factory
    with session_factory() as session:
        user = session.get(UserRecord, settings.development_user_id)
        if user is None:
            user = UserRecord(
                id=settings.development_user_id,
                auth_provider="development",
                auth_subject=settings.development_user_id,
                display_name="Development User",
                status=UserStatus.ACTIVE.value,
            )
            session.add(user)
        workspace = session.get(WorkspaceRecord, settings.development_workspace_id)
        if workspace is None:
            workspace = WorkspaceRecord(
                id=settings.development_workspace_id,
                name=settings.development_workspace_name,
                status=WorkspaceStatus.ACTIVE.value,
                created_by_user_id=user.id,
            )
            session.add(workspace)
            session.flush()
        if (
            session.get(
                WorkspaceMemberRecord,
                (settings.development_workspace_id, settings.development_user_id),
            )
            is None
        ):
            session.add(
                WorkspaceMemberRecord(
                    workspace_id=settings.development_workspace_id,
                    user_id=settings.development_user_id,
                    role=MembershipRole.OWNER.value,
                    status=MembershipStatus.ACTIVE.value,
                )
            )
        if session.get(WorkspaceLimitRecord, settings.development_workspace_id) is None:
            session.add(
                WorkspaceLimitRecord(workspace_id=settings.development_workspace_id)
            )
        if (
            session.get(WorkspaceCreditAccountRecord, settings.development_workspace_id)
            is None
        ):
            session.add(
                WorkspaceCreditAccountRecord(
                    workspace_id=settings.development_workspace_id
                )
            )
        session.commit()


def get_principal(
    request: Request,
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
) -> Principal:
    settings = request.app.state.settings
    if settings.auth_mode == "development":
        return Principal(user_id=x_user_id or settings.development_user_id)
    raise ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "AUTH_NOT_CONFIGURED",
        "身份服务尚未配置。",
    )


def require_workspace(
    workspace_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
    session: SessionDependency,
) -> WorkspaceContext:
    membership = session.scalar(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == workspace_id,
            WorkspaceMemberRecord.user_id == principal.user_id,
            WorkspaceMemberRecord.status == MembershipStatus.ACTIVE.value,
        )
    )
    workspace = session.get(WorkspaceRecord, workspace_id)
    if (
        workspace is None
        or workspace.status != WorkspaceStatus.ACTIVE.value
        or membership is None
    ):
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "WORKSPACE_NOT_FOUND",
            "未找到指定工作区。",
        )
    return WorkspaceContext(
        principal=principal,
        workspace_id=workspace_id,
        role=MembershipRole(membership.role),
    )


WorkspaceDependency = Annotated[WorkspaceContext, Depends(require_workspace)]
