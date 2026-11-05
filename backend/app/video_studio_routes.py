"""Video persistence only: no generation, provider calls or media uploads."""

import hashlib
import json
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .auth import (
    SessionDependency,
    WorkspaceContext,
    require_workspace,
    require_workspace_write,
)
from .errors import ApiError
from .models import utc_now
from .video_studio_access import VideoStudioDependency, require_video_studio_access
from .video_studio_models import (
    VideoMutationRecord,
    VideoProjectRecord,
    VideoScriptVersionRecord,
    VideoTaskRecord,
)
from .video_studio_schemas import (
    VideoLegacyImport,
    VideoProjectContent,
    VideoProjectResponse,
    VideoProjectWrite,
    VideoTaskResponse,
    VideoVersionResponse,
    VideoWriteResponse,
)

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-studio"],
    dependencies=[Depends(require_video_studio_access)],
)


def video_workspace(
    workspace_id: str, principal: VideoStudioDependency, session: SessionDependency
) -> WorkspaceContext:
    return require_workspace(workspace_id, principal, session)


VideoWorkspace = Annotated[WorkspaceContext, Depends(video_workspace)]


def scope(
    workspace: WorkspaceContext,
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (
        VideoProjectRecord.workspace_id == workspace.workspace_id,
        VideoProjectRecord.owner_user_id == workspace.principal.user_id,
    )


def project_response(project: VideoProjectRecord) -> VideoProjectResponse:
    return VideoProjectResponse(
        id=project.id,
        workspace_id=project.workspace_id,
        revision=project.revision,
        content=VideoProjectContent.model_validate(project.content),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def version_response(version: VideoScriptVersionRecord) -> VideoVersionResponse:
    return VideoVersionResponse(
        id=version.id,
        project_id=version.project_id,
        kind=cast(Literal["draft", "library", "confirmed"], version.kind),
        snapshot=VideoProjectContent.model_validate(version.snapshot),
        created_at=version.created_at,
    )


def task_response(
    task: VideoTaskRecord, version: VideoScriptVersionRecord
) -> VideoTaskResponse:
    return VideoTaskResponse(
        id=task.id,
        project_id=task.project_id,
        confirmed_version_id=task.confirmed_version_id,
        status="demo",
        snapshot=VideoProjectContent.model_validate(version.snapshot),
        created_at=task.created_at,
    )


def digest(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def replay(
    session: Session, workspace: WorkspaceContext, request_id: UUID, fingerprint: str
) -> VideoWriteResponse | None:
    row = session.get(
        VideoMutationRecord,
        (workspace.workspace_id, workspace.principal.user_id, str(request_id)),
    )
    if row:
        if row.request_hash != fingerprint:
            raise ApiError(
                409, "VIDEO_REQUEST_REUSED", "保存请求已用于其他内容，请重新保存。"
            )
        return VideoWriteResponse.model_validate(row.result)
    return None


def remember(
    session: Session,
    workspace: WorkspaceContext,
    request_id: UUID,
    fingerprint: str,
    result: VideoWriteResponse,
) -> None:
    session.add(
        VideoMutationRecord(
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            request_id=str(request_id),
            request_hash=fingerprint,
            result=result.model_dump(mode="json"),
        )
    )


def append_version(
    session: Session,
    project_id: str,
    content: dict[str, Any],
    kind: Literal["draft", "library", "confirmed"],
) -> VideoScriptVersionRecord:
    version = VideoScriptVersionRecord(
        id=str(uuid4()), project_id=project_id, kind=kind, snapshot=content
    )
    session.add(version)
    session.flush()
    return version


def append_demo(
    session: Session, project_id: str, content: dict[str, Any]
) -> tuple[VideoScriptVersionRecord, VideoTaskRecord]:
    version = append_version(session, project_id, content, "confirmed")
    task = VideoTaskRecord(
        id=str(uuid4()),
        project_id=project_id,
        confirmed_version_id=version.id,
        status="demo",
    )
    session.add(task)
    session.flush()
    return version, task


@router.get("/projects", response_model=list[VideoProjectResponse])
def projects(
    workspace: VideoWorkspace,
    session: SessionDependency,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[VideoProjectResponse]:
    rows = session.scalars(
        select(VideoProjectRecord)
        .where(*scope(workspace))
        .order_by(VideoProjectRecord.updated_at.desc(), VideoProjectRecord.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [project_response(row) for row in rows]


@router.get("/projects/{project_id}", response_model=VideoProjectResponse)
def project(
    project_id: UUID, workspace: VideoWorkspace, session: SessionDependency
) -> VideoProjectResponse:
    row = session.scalar(
        select(VideoProjectRecord).where(
            VideoProjectRecord.id == str(project_id), *scope(workspace)
        )
    )
    if row is None:
        raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
    return project_response(row)


@router.put("/projects/{project_id}", response_model=VideoWriteResponse)
def save_project(
    project_id: UUID,
    body: VideoProjectWrite,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> VideoWriteResponse:
    require_workspace_write(workspace)
    fingerprint = digest(
        {"project_id": str(project_id), **body.model_dump(mode="json")}
    )
    previous = replay(session, workspace, body.request_id, fingerprint)
    if previous:
        return previous
    row = session.get(VideoProjectRecord, str(project_id))
    if row and (
        row.workspace_id != workspace.workspace_id
        or row.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
    if (
        body.action in {"library", "demo"}
        and not body.content.draft.text.strip()
        and body.content.draft.drive == "text"
    ):
        raise ApiError(422, "VIDEO_SCRIPT_EMPTY", "请先填写文案。")
    content = body.content.model_dump(mode="json")
    old_content = row.content if row else None
    try:
        if row is None:
            if body.expected_revision != 0:
                raise ApiError(
                    409, "VIDEO_REVISION_CONFLICT", "项目已变化，请重新载入。"
                )
            row = VideoProjectRecord(
                id=str(project_id),
                workspace_id=workspace.workspace_id,
                owner_user_id=workspace.principal.user_id,
                revision=1,
                content=content,
            )
            session.add(row)
            session.flush()
        else:
            result = session.execute(
                update(VideoProjectRecord)
                .where(
                    VideoProjectRecord.id == row.id,
                    VideoProjectRecord.revision == body.expected_revision,
                )
                .values(
                    content=content,
                    revision=body.expected_revision + 1,
                    updated_at=utc_now(),
                )
                .execution_options(synchronize_session=False)
            )
            if cast(CursorResult, result).rowcount != 1:
                session.rollback()
                previous = replay(session, workspace, body.request_id, fingerprint)
                if previous:
                    return previous
                raise ApiError(
                    409,
                    "VIDEO_REVISION_CONFLICT",
                    "另一设备已更新项目，本次内容未覆盖，请另存或重新载入。",
                )
            session.refresh(row)
        version = None
        task = None
        if old_content != content:
            append_version(session, row.id, content, "draft")
        if body.action == "library":
            version = append_version(session, row.id, content, "library")
        if body.action == "demo":
            version, task = append_demo(session, row.id, content)
        response = VideoWriteResponse(
            project=project_response(row),
            version=version_response(version) if version else None,
            task=task_response(task, version) if task and version else None,
        )
        remember(session, workspace, body.request_id, fingerprint, response)
        session.commit()
        return response
    except IntegrityError:
        session.rollback()
        previous = replay(session, workspace, body.request_id, fingerprint)
        if previous:
            return previous
        raise ApiError(
            409, "VIDEO_REVISION_CONFLICT", "保存发生冲突，请重新载入或另存项目。"
        ) from None


@router.get("/versions", response_model=list[VideoVersionResponse])
def versions(
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID | None = None,
    kind: str = Query("library", pattern="^(draft|library|confirmed)$"),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[VideoVersionResponse]:
    query = (
        select(VideoScriptVersionRecord)
        .join(VideoProjectRecord)
        .where(*scope(workspace), VideoScriptVersionRecord.kind == kind)
    )
    if project_id:
        query = query.where(VideoProjectRecord.id == str(project_id))
    rows = session.scalars(
        query.order_by(
            VideoScriptVersionRecord.created_at.desc(), VideoScriptVersionRecord.id
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return [version_response(row) for row in rows]


@router.get("/tasks", response_model=list[VideoTaskResponse])
def tasks(
    workspace: VideoWorkspace,
    session: SessionDependency,
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[VideoTaskResponse]:
    rows = session.execute(
        select(VideoTaskRecord, VideoScriptVersionRecord)
        .join(
            VideoScriptVersionRecord,
            VideoTaskRecord.confirmed_version_id == VideoScriptVersionRecord.id,
        )
        .join(VideoProjectRecord, VideoTaskRecord.project_id == VideoProjectRecord.id)
        .where(*scope(workspace))
        .order_by(VideoTaskRecord.created_at.desc(), VideoTaskRecord.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [task_response(task, version) for task, version in rows]


@router.post("/imports/legacy", response_model=VideoWriteResponse)
def import_legacy(
    body: VideoLegacyImport, workspace: VideoWorkspace, session: SessionDependency
) -> VideoWriteResponse:
    require_workspace_write(workspace)
    fingerprint = digest({"import": body.model_dump(mode="json")})
    previous = replay(session, workspace, body.request_id, fingerprint)
    if previous:
        return previous
    content = VideoProjectContent(draft=body.draft).model_dump(mode="json")
    row = VideoProjectRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        revision=1,
        content=content,
    )
    session.add(row)
    session.flush()
    append_version(session, row.id, content, "draft")
    for copy in body.copies:
        snapshot = VideoProjectContent(
            draft=body.draft.model_copy(update={"name": copy.title, "text": copy.text})
        ).model_dump(mode="json")
        append_version(session, row.id, snapshot, "library")
    for work in body.works:
        append_demo(
            session,
            row.id,
            VideoProjectContent(draft=work.draft).model_dump(mode="json"),
        )
    response = VideoWriteResponse(project=project_response(row))
    remember(session, workspace, body.request_id, fingerprint, response)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        previous = replay(session, workspace, body.request_id, fingerprint)
        if previous:
            return previous
        raise
    return response
