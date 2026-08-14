from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .announcement_schemas import (
    AnnouncementAdminAccessResponse,
    AnnouncementCreate,
    AnnouncementKind,
    AnnouncementListResponse,
    AnnouncementResponse,
    AnnouncementStatus,
    AnnouncementUpdate,
)
from .auth import Principal, get_principal
from .database import get_session
from .domain import MembershipRole, MembershipStatus
from .errors import ApiError
from .models import AnnouncementRecord, WorkspaceMemberRecord
from .services import new_id

router = APIRouter(prefix="/api/v1")
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[Principal, Depends(get_principal)]

_ADMIN_ROLES = {MembershipRole.OWNER.value, MembershipRole.ADMIN.value}


def _now() -> datetime:
    return datetime.now(UTC)


def _announcement_response(record: AnnouncementRecord) -> AnnouncementResponse:
    return AnnouncementResponse(
        id=record.id,
        title=record.title,
        summary=record.summary,
        content=record.content,
        kind=cast(AnnouncementKind, record.kind),
        status=cast(AnnouncementStatus, record.status),
        link_url=record.link_url,
        starts_at=record.starts_at,
        ends_at=record.ends_at,
        is_pinned=record.is_pinned,
        published_at=record.published_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _active_filters(now: datetime) -> tuple[ColumnElement[bool], ...]:
    return (
        AnnouncementRecord.status == "published",
        (
            AnnouncementRecord.starts_at.is_(None)
            | (AnnouncementRecord.starts_at <= now)
        ),
        (AnnouncementRecord.ends_at.is_(None) | (AnnouncementRecord.ends_at > now)),
    )


def _is_announcement_admin(principal: Principal, session: Session) -> bool:
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


def require_announcement_admin(
    principal: PrincipalDependency,
    session: SessionDependency,
) -> Principal:
    if not _is_announcement_admin(principal, session):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "ANNOUNCEMENT_ADMIN_REQUIRED",
            "An active workspace owner or admin role is required to manage "
            "announcements.",
        )
    return principal


AnnouncementAdminDependency = Annotated[Principal, Depends(require_announcement_admin)]


def _get_admin_announcement(
    announcement_id: str,
    session: Session,
) -> AnnouncementRecord:
    record = session.get(AnnouncementRecord, announcement_id)
    if record is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "ANNOUNCEMENT_NOT_FOUND",
            "The announcement was not found.",
        )
    return record


def _validate_record(record: AnnouncementRecord) -> None:
    if not record.title.strip() or not record.content.strip():
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "ANNOUNCEMENT_CONTENT_REQUIRED",
            "Announcement title and content are required.",
        )
    if (
        record.starts_at is not None
        and record.ends_at is not None
        and record.ends_at <= record.starts_at
    ):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "ANNOUNCEMENT_INVALID_WINDOW",
            "The end time must be later than the start time.",
        )


@router.get(
    "/announcements/current",
    response_model=AnnouncementResponse | None,
    tags=["announcements"],
)
def get_current_announcement(session: SessionDependency) -> AnnouncementResponse | None:
    record = session.scalar(
        select(AnnouncementRecord)
        .where(*_active_filters(_now()))
        .order_by(
            AnnouncementRecord.is_pinned.desc(),
            AnnouncementRecord.published_at.desc(),
            AnnouncementRecord.created_at.desc(),
        )
        .limit(1)
    )
    return _announcement_response(record) if record is not None else None


@router.get(
    "/announcements",
    response_model=AnnouncementListResponse,
    tags=["announcements"],
)
def list_public_announcements(
    session: SessionDependency,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> AnnouncementListResponse:
    records = session.scalars(
        select(AnnouncementRecord)
        .where(*_active_filters(_now()))
        .order_by(
            AnnouncementRecord.is_pinned.desc(),
            AnnouncementRecord.published_at.desc(),
            AnnouncementRecord.created_at.desc(),
        )
        .limit(limit)
    ).all()
    return AnnouncementListResponse(
        items=[_announcement_response(item) for item in records]
    )


@router.get(
    "/admin/announcements/access",
    response_model=AnnouncementAdminAccessResponse,
    tags=["announcements-admin"],
)
def get_announcement_admin_access(
    principal: PrincipalDependency,
    session: SessionDependency,
) -> AnnouncementAdminAccessResponse:
    return AnnouncementAdminAccessResponse(
        can_manage=_is_announcement_admin(principal, session)
    )


@router.get(
    "/admin/announcements",
    response_model=AnnouncementListResponse,
    tags=["announcements-admin"],
)
def list_admin_announcements(
    session: SessionDependency,
    _admin: AnnouncementAdminDependency,
    status_filter: Annotated[
        Literal["all", "draft", "published", "archived"], Query(alias="status")
    ] = "all",
) -> AnnouncementListResponse:
    filters: list[ColumnElement[bool]] = []
    if status_filter != "all":
        filters.append(AnnouncementRecord.status == status_filter)
    statement = select(AnnouncementRecord)
    if filters:
        statement = statement.where(*filters)
    records = session.scalars(
        statement.order_by(
            AnnouncementRecord.updated_at.desc(),
            AnnouncementRecord.created_at.desc(),
        )
    ).all()
    return AnnouncementListResponse(
        items=[_announcement_response(item) for item in records]
    )


@router.post(
    "/admin/announcements",
    response_model=AnnouncementResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["announcements-admin"],
)
def create_announcement(
    payload: AnnouncementCreate,
    session: SessionDependency,
    admin: AnnouncementAdminDependency,
) -> AnnouncementResponse:
    record = AnnouncementRecord(
        id=new_id("ann"),
        title=payload.title.strip(),
        summary=payload.summary.strip() if payload.summary else None,
        content=payload.content.strip(),
        kind=payload.kind,
        status="draft",
        link_url=str(payload.link_url) if payload.link_url else None,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        is_pinned=payload.is_pinned,
        created_by_user_id=admin.user_id,
        updated_by_user_id=admin.user_id,
    )
    _validate_record(record)
    session.add(record)
    session.commit()
    session.refresh(record)
    return _announcement_response(record)


@router.patch(
    "/admin/announcements/{announcement_id}",
    response_model=AnnouncementResponse,
    tags=["announcements-admin"],
)
def update_announcement(
    announcement_id: str,
    payload: AnnouncementUpdate,
    session: SessionDependency,
    admin: AnnouncementAdminDependency,
) -> AnnouncementResponse:
    record = _get_admin_announcement(announcement_id, session)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if key == "link_url":
            value = str(value) if value else None
        if isinstance(value, str):
            value = value.strip()
        setattr(record, key, value)
    _validate_record(record)
    record.updated_by_user_id = admin.user_id
    session.commit()
    session.refresh(record)
    return _announcement_response(record)


@router.post(
    "/admin/announcements/{announcement_id}/publish",
    response_model=AnnouncementResponse,
    tags=["announcements-admin"],
)
def publish_announcement(
    announcement_id: str,
    session: SessionDependency,
    admin: AnnouncementAdminDependency,
) -> AnnouncementResponse:
    record = _get_admin_announcement(announcement_id, session)
    _validate_record(record)
    record.status = "published"
    record.published_at = record.published_at or _now()
    record.updated_by_user_id = admin.user_id
    session.commit()
    session.refresh(record)
    return _announcement_response(record)


@router.post(
    "/admin/announcements/{announcement_id}/archive",
    response_model=AnnouncementResponse,
    tags=["announcements-admin"],
)
def archive_announcement(
    announcement_id: str,
    session: SessionDependency,
    admin: AnnouncementAdminDependency,
) -> AnnouncementResponse:
    record = _get_admin_announcement(announcement_id, session)
    record.status = "archived"
    record.is_pinned = False
    record.updated_by_user_id = admin.user_id
    session.commit()
    session.refresh(record)
    return _announcement_response(record)
