"""Upload and read current-project supplemental media with original bytes."""

import asyncio
import math
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from .auth import SessionDependency, require_workspace_write
from .config import Settings
from .errors import ApiError
from .motion_library import sha256
from .storage import UploadValidationError
from .video_editing_contracts import EditingMaterialResponse, EditingMaterialsResponse
from .video_editing_materials import (
    PREFIX,
    SUFFIXES,
    material_file,
    verify_material_file,
)
from .video_editing_pipeline import probe
from .video_editing_task_models import EditingMaterialRecord
from .video_editing_task_routes import enabled, own_project
from .video_studio_routes import VideoWorkspace

ROOT = (
    "/api/v1/video-studio/workspaces/{workspace_id}"
    "/projects/{project_id}/editing-materials"
)
router = APIRouter(prefix=ROOT, tags=["video-editing-materials"])


def metadata(path: Path, mime: str, settings: Settings) -> tuple[int, int, int]:
    try:
        data = probe(path, settings)
        videos = [
            row
            for row in data["streams"]
            if row.get("codec_type") == "video"
            and not row.get("disposition", {}).get("attached_pic")
        ]
        (stream,) = videos
        width, height = int(stream["width"]), int(stream["height"])
        fmt = data["format"]
        duration = float(stream.get("duration") or fmt["duration"])
        start = float(stream.get("start_time") or 0)
        rate, scale = (int(part) for part in stream["avg_frame_rate"].split("/"))
        formats = fmt["format_name"].split(",")
        if (
            ("webm" if mime == "video/webm" else "mov") not in formats
            or not 0 < width * height <= 4096 * 2160
            or not 0 < duration <= 300
            or not math.isfinite(start)
            or abs(start) > 0.05
            or not 0 < rate / scale <= 120
            or any(side.get("rotation", 0) for side in stream.get("side_data_list", []))
        ):
            raise ValueError("Unsupported supplemental video")
    except FileNotFoundError as error:
        raise ApiError(
            503,
            "EDITING_MATERIAL_PROBE_UNAVAILABLE",
            "剪辑服务缺少视频素材检查工具，请联系管理员。",
        ) from error
    except (
        subprocess.SubprocessError,
        ValueError,
        TypeError,
        KeyError,
        ZeroDivisionError,
        OSError,
    ) as error:
        raise ApiError(
            422,
            "EDITING_MATERIAL_VIDEO_INVALID",
            "请选择起点与方向已校正、最长 5 分钟的 MP4、MOV 或 WebM 素材。",
        ) from error
    return width, height, round(duration * 1000)


def response(row: EditingMaterialRecord) -> dict:
    return {
        **{
            key: getattr(row, key)
            for key in (
                "id",
                "label",
                "description",
                "kind",
                "mime",
                "sha256",
                "bytes",
                "width",
                "height",
                "duration_ms",
            )
        },
        "asset_id": PREFIX + row.id,
        "url": ROOT.format(workspace_id=row.workspace_id, project_id=row.project_id)
        + f"/{row.id}/file",
    }


def scope(
    workspace: VideoWorkspace, project_id: UUID
) -> tuple[ColumnElement[bool], ...]:
    return (
        EditingMaterialRecord.workspace_id == workspace.workspace_id,
        EditingMaterialRecord.owner_user_id == workspace.principal.user_id,
        EditingMaterialRecord.project_id == str(project_id),
    )


@router.get("", response_model=EditingMaterialsResponse)
def list_materials(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    enabled(request)
    own_project(session, workspace, str(project_id))
    rows = session.scalars(
        select(EditingMaterialRecord)
        .where(*scope(workspace, project_id))
        .order_by(
            EditingMaterialRecord.created_at.desc(),
            EditingMaterialRecord.id.desc(),
        )
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return {
        "items": [response(row) for row in rows[:limit]],
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@router.post("", response_model=EditingMaterialResponse, status_code=201)
async def upload_material(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID,
    file: Annotated[UploadFile, File()],
    request_id: Annotated[UUID, Form()],
    label: Annotated[str, Form(min_length=1, max_length=120)],
    description: Annotated[str, Form(min_length=1, max_length=400)],
) -> dict:
    require_workspace_write(workspace)
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    label, description = label.strip(), description.strip()
    if not label or not description:
        raise ApiError(
            422,
            "EDITING_MATERIAL_DESCRIPTION_REQUIRED",
            "请填写素材名称与实际画面说明。",
        )
    mime = file.content_type or ""
    if mime not in SUFFIXES:
        raise ApiError(
            422, "EDITING_MATERIAL_TYPE", "请上传 JPG、PNG、WebP、MP4、MOV 或 WebM。"
        )
    kind = mime.split("/", 1)[0]
    material_id = str(uuid4())
    target: Path | None = None
    preserve = False
    identity = (
        *scope(workspace, project_id),
        EditingMaterialRecord.request_id == str(request_id),
    )
    duration = None
    try:
        if kind == "image":
            try:
                image = await request.app.state.image_validator.validate(
                    file, workspace.workspace_id
                )
            except UploadValidationError as error:
                raise ApiError(422, error.code, error.message) from error
            mime, width, height = image.content_type, image.width, image.height
            length, digest = len(image.payload), image.sha256
            target = material_file(settings, material_id, mime)
            target.parent.mkdir(parents=True)
            target.write_bytes(image.payload)
        else:
            target = material_file(settings, material_id, mime)
            target.parent.mkdir(parents=True)
            length = 0
            with target.open("xb") as fd:
                while chunk := await file.read(1024 * 1024):
                    length += len(chunk)
                    if length > 500 * 1024 * 1024:
                        raise ApiError(
                            413,
                            "EDITING_MATERIAL_TOO_LARGE",
                            "视频素材不能超过 500 MB。",
                        )
                    fd.write(chunk)
            width, height, duration = await asyncio.to_thread(
                metadata, target, mime, settings
            )
            digest = await asyncio.to_thread(sha256, target)
        row = EditingMaterialRecord(
            id=material_id,
            request_id=str(request_id),
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            project_id=str(project_id),
            kind=kind,
            mime=mime,
            sha256=digest,
            bytes=length,
            label=label,
            description=description,
            width=width,
            height=height,
            duration_ms=duration,
        )
        session.add(row)
        # Keep the immutable original if the database commit outcome is uncertain.
        preserve = True
        try:
            session.commit()
        except IntegrityError:
            preserve = False
            session.rollback()
            old = session.scalar(select(EditingMaterialRecord).where(*identity))
            if old and (old.sha256, old.mime, old.label, old.description) == (
                digest,
                mime,
                label,
                description,
            ):
                return response(old)
            raise ApiError(
                409, "EDITING_MATERIAL_REQUEST_REUSED", "素材请求编号已用于其他输入。"
            ) from None
        return response(row)
    finally:
        await file.close()
        if target and not preserve:
            with suppress(OSError):
                target.unlink(missing_ok=True)
                target.parent.rmdir()


@router.get("/{material_id}/file")
def original(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID,
    material_id: UUID,
) -> FileResponse:
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    row = session.scalar(
        select(EditingMaterialRecord).where(
            *scope(workspace, project_id), EditingMaterialRecord.id == str(material_id)
        )
    )
    if not row:
        raise ApiError(404, "EDITING_MATERIAL_NOT_FOUND", "未找到本项目的补充素材。")
    return FileResponse(
        verify_material_file(settings, row),
        media_type=row.mime,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
