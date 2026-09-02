from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .database import get_session
from .domain import MembershipRole, MembershipStatus
from .errors import ApiError
from .models import WorkspaceMemberRecord

_ADMIN_ROLES = {MembershipRole.OWNER.value, MembershipRole.ADMIN.value}

SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(get_principal)]


def is_admin(principal: Principal, session: Session, settings: object) -> bool:
    """Return whether a verified user is an active, allow-listed admin.

    The existing announcement allowlist is the current deployment-level admin
    configuration. Keeping the policy in one dependency lets future admin
    modules share the same boundary without duplicating authorization checks.
    """

    email = principal.email.strip().casefold() if principal.email else None
    allowlist = getattr(settings, "announcement_admin_emails", ())
    if (
        not principal.email_verified
        or email is None
        or email not in allowlist
    ):
        return False
    return (
        session.scalar(
            select(WorkspaceMemberRecord.user_id)
            .where(
                WorkspaceMemberRecord.user_id == principal.user_id,
                WorkspaceMemberRecord.status == MembershipStatus.ACTIVE.value,
                WorkspaceMemberRecord.role.in_(_ADMIN_ROLES),
            )
            .limit(1)
        )
        is not None
    )


def require_admin(
    request: Request,
    principal: PrincipalDependency,
    session: SessionDependency,
) -> Principal:
    if not is_admin(principal, session, request.app.state.settings):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "ADMIN_REQUIRED",
            "An active workspace owner or admin role is required.",
        )
    return principal


AdminDependency = Annotated[Principal, Depends(require_admin)]
