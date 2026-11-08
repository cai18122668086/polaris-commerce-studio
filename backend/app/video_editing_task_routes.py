"""Owner-scoped editing API. All decoding, ASR and rendering run in a worker."""

from datetime import UTC
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .config import Settings
from .errors import ApiError
from .motion_library import MOTION_SHA256, read_json, sha256
from .motion_library_validation import group_status
from .motion_parameter_contracts import input_contract
from .video_editing_contracts import EditingTaskCreate, EditingTaskResponse
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_generation import own_job
from .video_studio_models import VideoProjectRecord, VideoScriptVersionRecord
from .video_studio_routes import VideoWorkspace, digest

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-editing-tasks"],
)


def enabled(request: Request) -> Settings:
    settings = request.app.state.settings
    if not settings.video_editing_enabled:
        raise ApiError(503, "EDITING_DISABLED", "剪辑服务尚未开放。")
    package = settings.video_editing_library_dir
    if not (package / "adapter.py").is_file():
        raise ApiError(503, "EDITING_LIBRARY_MISSING", "剪辑原库尚未安装。")
    return settings


def own_project(
    session: Session, workspace: WorkspaceContext, project_id: str
) -> VideoProjectRecord:
    project = session.get(VideoProjectRecord, project_id)
    if (
        not project
        or project.workspace_id != workspace.workspace_id
        or project.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
    return project


def own_task(
    session: Session, workspace: WorkspaceContext, task_id: str
) -> EditingTaskRecord:
    row = session.get(EditingTaskRecord, task_id)
    if (
        not row
        or row.workspace_id != workspace.workspace_id
        or row.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "EDITING_NOT_FOUND", "未找到剪辑任务。")
    return row


def response(row: EditingTaskRecord, session: Session) -> dict[str, Any]:
    base = f"/api/v1/video-studio/workspaces/{row.workspace_id}/editing-tasks/{row.id}"
    artifacts = session.scalars(
        select(EditingArtifactRecord).where(EditingArtifactRecord.task_id == row.id)
    ).all()
    return {
        "id": row.id,
        "project_id": row.project_id,
        "source_id": row.source_id,
        "status": row.status,
        "stage": row.stage,
        "revision": row.revision,
        "attempts": row.attempts,
        "error_code": row.error_code,
        "cancel_requested": row.cancel_requested,
        "created_at": row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
        "library_release": row.library_release,
        "options": row.options,
        "review": {
            "semantic": "unreviewed",
            "visual": "unreviewed",
            "timing": "unreviewed",
        },
        "artifacts": [
            {
                "id": a.id,
                "role": a.role,
                "mime": a.mime,
                "sha256": a.sha256,
                "bytes": a.bytes,
                "duration_ms": a.duration_ms,
                "url": base + "/artifacts/" + a.id,
            }
            for a in artifacts
        ]
        if row.status == "completed"
        else [],
    }


def dispatch(request: Request, task_id: str) -> None:
    """Production delivery belongs to maintenance, never the request thread.

    The committed task is the durable outbox. A broker outage must not make a
    successful create request hang and tempt users to submit a duplicate job.
    """
    callback = getattr(request.app.state, "editing_dispatcher", None)
    if callback:
        callback(task_id)


@router.get("/editing-library")
def library(
    request: Request,
    workspace: VideoWorkspace,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=132),
) -> dict[str, Any]:
    settings = enabled(request)
    package = settings.video_editing_library_dir
    catalog = read_json(package / "catalog/groups.json")
    return {
        "release": MOTION_SHA256,
        "total": len(catalog["groups"]),
        "bundled_assets": len(read_json(package / "asset-manifest.json")["assets"]),
        "external_references": len(
            read_json(package / "catalog/external-resources.json")["resources"]
        ),
        "groups": [
            {
                **g,
                **group_status(
                    settings.video_editing_tasks_dir
                    / "_library-validation"
                    / MOTION_SHA256[:12],
                    g["id"],
                ),
            }
            for g in catalog["groups"][offset : offset + limit]
        ],
        "next_offset": offset + limit
        if offset + limit < len(catalog["groups"])
        else None,
    }


@router.post("/editing-sources")
async def upload_source(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: Annotated[UUID, Form()],
    file: Annotated[UploadFile, File()],
    confirmed_version_id: Annotated[UUID | None, Form()] = None,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    if confirmed_version_id:
        version = session.get(VideoScriptVersionRecord, str(confirmed_version_id))
        if (
            not version
            or version.project_id != str(project_id)
            or version.kind != "confirmed"
        ):
            raise ApiError(422, "EDITING_SCRIPT_INVALID", "请选择本项目的确认稿版本。")
    if file.content_type not in {"video/mp4", "video/quicktime", "video/webm"}:
        raise ApiError(422, "EDITING_SOURCE_TYPE", "请上传 MP4、MOV 或 WebM 视频。")
    sid = str(uuid4())
    target = settings.video_editing_tasks_dir / "sources" / sid / "source.media"
    target.parent.mkdir(parents=True)
    length = 0
    try:
        with target.open("xb") as out:
            while block := await file.read(1024 * 1024):
                length += len(block)
                if length > 500 * 1024 * 1024:
                    raise ApiError(
                        413, "EDITING_SOURCE_TOO_LARGE", "视频不能超过 500 MB。"
                    )
                out.write(block)
        if length == 0:
            raise ApiError(422, "EDITING_SOURCE_EMPTY", "视频文件为空。")
        row = EditingSourceRecord(
            id=sid,
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            project_id=str(project_id),
            confirmed_version_id=str(confirmed_version_id)
            if confirmed_version_id
            else None,
            kind="upload_asset",
            media_path=str(target.resolve()),
            media_sha256=sha256(target),
            details={"mime": file.content_type, "bytes": length},
        )
        session.add(row)
        session.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return {
        "id": row.id,
        "project_id": row.project_id,
        "sha256": row.media_sha256,
        "bytes": length,
    }


@router.get("/editing-library/groups/{group_id}")
def describe_group(
    group_id: str, request: Request, workspace: VideoWorkspace
) -> dict[str, Any]:
    settings = enabled(request)
    package = settings.video_editing_library_dir
    catalog = read_json(package / "catalog/groups.json")
    canonical = catalog.get("aliases", {}).get(group_id, group_id)
    group = next((g for g in catalog["groups"] if g["id"] == canonical), None)
    if not group:
        raise ApiError(404, "EDITING_GROUP_NOT_FOUND", "未找到原库动效。")
    return {
        "release": MOTION_SHA256,
        "group": group,
        "input_schema": read_json(package / group["input_schema"]),
        "parameter_contract": input_contract(package, group),
        "contract": read_json(package / group["contract"])
        if group.get("contract")
        else None,
        "contract_status": "declared"
        if group.get("contract")
        else "inspect_native_schema_and_entry",
        **group_status(
            settings.video_editing_tasks_dir
            / "_library-validation"
            / MOTION_SHA256[:12],
            group["id"],
        ),
        "historical_input_not_used_as_new_defaults": True,
    }


@router.get("/editing-library/resources")
def library_resources(
    request: Request,
    workspace: VideoWorkspace,
    source: str = Query(default="bundled", pattern="^(bundled|external)$"),
    kind: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    package = enabled(request).video_editing_library_dir
    rows = (
        read_json(package / "asset-manifest.json")["assets"]
        if source == "bundled"
        else read_json(package / "catalog/external-resources.json")["resources"]
    )
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    return {
        "release": MOTION_SHA256,
        "source": source,
        "total": len(rows),
        "resources": rows[offset : offset + limit],
        "next_offset": offset + limit if offset + limit < len(rows) else None,
        "external_files_available": False if source == "external" else None,
        "website_runtime_validation": "unverified",
    }


@router.post("/editing-tasks", response_model=EditingTaskResponse)
def create_task(
    body: EditingTaskCreate,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    enabled(request)
    fingerprint = digest(
        {**body.model_dump(mode="json"), "library_release": MOTION_SHA256}
    )
    previous = session.scalar(
        select(EditingTaskRecord).where(
            EditingTaskRecord.workspace_id == workspace.workspace_id,
            EditingTaskRecord.owner_user_id == workspace.principal.user_id,
            EditingTaskRecord.request_id == str(body.request_id),
        )
    )
    if previous:
        if previous.request_hash != fingerprint:
            raise ApiError(
                409, "EDITING_REQUEST_REUSED", "此请求编号已用于不同的剪辑内容。"
            )
        return response(previous, session)
    source: EditingSourceRecord | None
    if body.generation_task_id:
        job = own_job(session, workspace, body.generation_task_id)
        if job.kind != "lipsync" or job.status != "completed" or not job.project_id:
            raise ApiError(409, "EDITING_SOURCE_NOT_READY", "请选择已完成的口播视频。")
        own_project(session, workspace, job.project_id)
        path = Path(job.details.get("result_path", ""))
        if not path.is_file():
            raise ApiError(
                409, "EDITING_SOURCE_MISSING", "原片暂不可用，请恢复原任务。"
            )
        source = EditingSourceRecord(
            id=str(uuid4()),
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            project_id=job.project_id,
            confirmed_version_id=job.confirmed_version_id,
            generation_task_id=job.id,
            kind="generation_task",
            media_path=str(path.resolve()),
            media_sha256=sha256(path),
            details={
                "audio_policy": "source_video_audio",
                "generation_task_id": job.id,
            },
        )
        session.add(source)
    else:
        source = session.get(EditingSourceRecord, str(body.source_id))
        if (
            not source
            or source.workspace_id != workspace.workspace_id
            or source.owner_user_id != workspace.principal.user_id
        ):
            raise ApiError(404, "EDITING_SOURCE_NOT_FOUND", "未找到视频源。")
        own_project(session, workspace, source.project_id)
    row = EditingTaskRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=source.project_id,
        source_id=source.id,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        library_release=MOTION_SHA256,
        options=body.options.model_dump(),
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        concurrent = session.scalar(
            select(EditingTaskRecord).where(
                EditingTaskRecord.workspace_id == workspace.workspace_id,
                EditingTaskRecord.owner_user_id == workspace.principal.user_id,
                EditingTaskRecord.request_id == str(body.request_id),
            )
        )
        if concurrent and concurrent.request_hash == fingerprint:
            return response(concurrent, session)
        raise ApiError(
            409, "EDITING_TASK_CONFLICT", "剪辑请求发生冲突，请刷新任务后重试。"
        ) from None
    dispatch(request, row.id)
    return response(row, session)


@router.get("/editing-tasks", response_model=list[EditingTaskResponse])
def list_tasks(
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID | None = None,
) -> list[dict[str, Any]]:
    query = select(EditingTaskRecord).where(
        EditingTaskRecord.workspace_id == workspace.workspace_id,
        EditingTaskRecord.owner_user_id == workspace.principal.user_id,
    )
    if project_id:
        query = query.where(EditingTaskRecord.project_id == str(project_id))
    return [
        response(row, session)
        for row in session.scalars(
            query.order_by(EditingTaskRecord.created_at.desc()).limit(100)
        )
    ]


@router.get("/editing-tasks/{task_id}", response_model=EditingTaskResponse)
def get_task(
    task_id: UUID, workspace: VideoWorkspace, session: SessionDependency
) -> dict[str, Any]:
    return response(own_task(session, workspace, str(task_id)), session)


@router.post("/editing-tasks/{task_id}/cancel", response_model=EditingTaskResponse)
def cancel_task(
    task_id: UUID, workspace: VideoWorkspace, session: SessionDependency
) -> dict[str, Any]:
    require_workspace_write(workspace)
    row = own_task(session, workspace, str(task_id))
    session.execute(
        update(EditingTaskRecord)
        .execution_options(synchronize_session=False)
        .where(
            EditingTaskRecord.id == row.id,
            EditingTaskRecord.status.in_(["queued", "running"]),
        )
        .values(
            cancel_requested=True,
            revision=EditingTaskRecord.revision + 1,
            status=case(
                (EditingTaskRecord.status == "queued", "cancelled"),
                else_=EditingTaskRecord.status,
            ),
            stage=case(
                (EditingTaskRecord.status == "queued", "cancelled"),
                else_=EditingTaskRecord.stage,
            ),
        )
    )
    session.commit()
    session.refresh(row)
    return response(row, session)


@router.post("/editing-tasks/{task_id}/retry", response_model=EditingTaskResponse)
def retry_task(
    task_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    enabled(request)
    row = own_task(session, workspace, str(task_id))
    result = session.execute(
        update(EditingTaskRecord)
        .where(
            EditingTaskRecord.id == row.id,
            EditingTaskRecord.status.in_(["failed", "cancelled"]),
        )
        .values(
            status="queued",
            stage="queued",
            cancel_requested=False,
            error_code=None,
            owner_token=None,
            lease_until=None,
            checkpoint={**row.checkpoint, "dispatch_not_before": 0},
            revision=EditingTaskRecord.revision + 1,
        )
    )
    if not cast(CursorResult, result).rowcount:
        session.rollback()
        raise ApiError(409, "EDITING_RETRY_STATE", "只有失败或已取消的任务可以重试。")
    session.commit()
    session.refresh(row)
    dispatch(request, row.id)
    return response(row, session)


@router.get("/editing-tasks/{task_id}/artifacts/{artifact_id}")
def artifact(
    task_id: UUID,
    artifact_id: UUID,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> FileResponse:
    row = own_task(session, workspace, str(task_id))
    record = session.get(EditingArtifactRecord, str(artifact_id))
    if row.status != "completed" or not record or record.task_id != row.id:
        raise ApiError(404, "EDITING_ARTIFACT_NOT_FOUND", "未找到已校验的剪辑产物。")
    path = Path(record.path)
    if (
        not path.is_file()
        or path.stat().st_size != record.bytes
        or sha256(path) != record.sha256
    ):
        raise ApiError(409, "EDITING_ARTIFACT_MISSING", "剪辑产物暂不可用。")
    return FileResponse(
        path,
        media_type=record.mime,
        filename=f"{row.id}-{record.role}{path.suffix}",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )
