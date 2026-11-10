"""Register and read current-project supplemental media with original bytes."""

import asyncio
import math
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .auth import SessionDependency, require_workspace_write
from .config import Settings
from .domain import (
    AssetLifecycleStatus,
    AssetMediaKind,
    AssetOriginKind,
    JobAssetDirection,
    JobItemStatus,
    JobStatus,
    JobType,
)
from .errors import ApiError
from .local_edit_billing import require_image_access
from .models import AssetRecord, JobAssetRecord, JobItemRecord, JobRecord
from .motion_library import sha256
from .services import asset_is_available, job_history_is_available
from .storage import ALLOWED_IMAGE_FORMATS, ImageStorage, UploadValidationError
from .video_editing_contracts import (
    EditingFeedbackObservation,
    EditingImageResultImport,
    EditingMaterialResponse,
    EditingMaterialsResponse,
)
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
IMAGE_TYPES = frozenset(mime for _, mime in ALLOWED_IMAGE_FORMATS.values())


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
                "source_job_id",
                "source_asset_id",
                "feedback_observation",
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


def material_description(label: str, description: str) -> tuple[str, str]:
    label, description = label.strip(), description.strip()
    if not label or not description:
        raise ApiError(
            422,
            "EDITING_MATERIAL_DESCRIPTION_REQUIRED",
            "请填写素材名称与实际画面说明。",
        )
    return label, description


def material_intent(row: EditingMaterialRecord) -> tuple:
    return (
        row.label,
        row.description,
        row.source_job_id,
        row.source_asset_id,
        row.feedback_observation,
    )


def reused_request() -> ApiError:
    return ApiError(
        409, "EDITING_MATERIAL_REQUEST_REUSED", "素材请求编号已用于其他输入。"
    )


def remove_candidate(target: Path) -> None:
    with suppress(OSError):
        target.unlink(missing_ok=True)
        target.parent.rmdir()


def commit_material(
    session: Session,
    row: EditingMaterialRecord,
    target: Path,
    identity: tuple[ColumnElement[bool], ...],
) -> dict:
    expected = (*material_intent(row), row.sha256, row.mime)
    session.add(row)
    # Keep the immutable original if the database commit outcome is uncertain.
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        remove_candidate(target)
        old = session.scalar(select(EditingMaterialRecord).where(*identity))
        if old and (*material_intent(old), old.sha256, old.mime) == expected:
            return response(old)
        raise reused_request() from None
    return response(row)


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
    feedback_observation: Annotated[str | None, Form(max_length=1200)] = None,
) -> dict:
    require_workspace_write(workspace)
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    label, description = material_description(label, description)
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
        observation = None
        if feedback_observation is not None:
            try:
                observation = EditingFeedbackObservation.model_validate_json(
                    feedback_observation
                )
            except ValidationError:
                raise ApiError(
                    422,
                    "EDITING_FEEDBACK_OBSERVATION_INVALID",
                    "请填写反馈标签、实际点赞数、来源及带时区的观察时间，并确认记录。",
                ) from None
            if kind != "image":
                raise ApiError(
                    422,
                    "EDITING_FEEDBACK_EVIDENCE_IMAGE_REQUIRED",
                    "互动记录需要上传对应的证据图片。",
                )
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
            feedback_observation=observation.model_dump(mode="json")
            if observation
            else None,
        )
        preserve = True
        return commit_material(session, row, target, identity)
    finally:
        await file.close()
        if target and not preserve:
            remove_candidate(target)


@router.post("/image-results", response_model=EditingMaterialResponse, status_code=201)
async def import_image_result(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID,
    body: EditingImageResultImport,
) -> dict:
    require_workspace_write(workspace)
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    label, description = material_description(body.label, body.description)
    identity = (
        *scope(workspace, project_id),
        EditingMaterialRecord.request_id == str(body.request_id),
    )
    old = session.scalar(select(EditingMaterialRecord).where(*identity))
    if old is not None:
        if material_intent(old) != (
            label,
            description,
            body.job_id,
            body.asset_id,
            None,
        ):
            raise reused_request()
        verify_material_file(settings, old)
        return response(old)

    asset = session.scalar(
        select(AssetRecord)
        .join(JobAssetRecord, JobAssetRecord.asset_id == AssetRecord.id)
        .join(JobRecord, JobRecord.id == JobAssetRecord.job_id)
        .join(JobItemRecord, JobItemRecord.id == JobAssetRecord.job_item_id)
        .where(
            AssetRecord.id == body.asset_id,
            AssetRecord.workspace_id == workspace.workspace_id,
            AssetRecord.media_kind == AssetMediaKind.IMAGE.value,
            AssetRecord.origin_kind == AssetOriginKind.GENERATED.value,
            AssetRecord.lifecycle_status == AssetLifecycleStatus.READY.value,
            asset_is_available(),
            JobAssetRecord.workspace_id == workspace.workspace_id,
            JobAssetRecord.direction == JobAssetDirection.OUTPUT.value,
            JobAssetRecord.is_deliverable.is_(True),
            JobRecord.workspace_id == workspace.workspace_id,
            JobRecord.id == body.job_id,
            JobRecord.type == JobType.CREATIVE_IMAGE.value,
            JobRecord.status.in_((JobStatus.COMPLETED.value, JobStatus.PARTIAL.value)),
            job_history_is_available(),
            JobItemRecord.workspace_id == workspace.workspace_id,
            JobItemRecord.job_id == body.job_id,
            JobItemRecord.status.in_(
                (JobItemStatus.SUCCEEDED.value, JobItemStatus.REUSED.value)
            ),
        )
    )
    if asset is None:
        raise ApiError(
            404, "EDITING_IMAGE_RESULT_NOT_FOUND", "未找到可导入的创意图成品。"
        )
    require_image_access(session, asset)
    session.expunge(asset)
    session.rollback()

    storage: ImageStorage = request.app.state.storage
    if (asset.storage_provider, asset.storage_bucket) != (
        storage.provider_name,
        storage.bucket_name,
    ):
        raise ApiError(
            409, "EDITING_IMAGE_RESULT_STORAGE", "创意图原件不在当前素材库。"
        )
    if (
        asset.content_type not in IMAGE_TYPES
        or asset.byte_size > settings.max_upload_bytes
    ):
        raise ApiError(
            422, "EDITING_IMAGE_RESULT_LIMIT", "图片格式或大小超出剪辑素材限制。"
        )
    try:
        payload, stored = await storage.read_stored_image(
            asset.object_key, asset.object_version
        )
    except (
        BotoCoreError,
        ClientError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
    ) as error:
        raise ApiError(
            409, "EDITING_IMAGE_RESULT_UNREADABLE", "无法核验创意图原件，请检查素材库。"
        ) from error
    if (
        stored.sha256,
        stored.byte_size,
        stored.content_type,
        stored.width,
        stored.height,
    ) != (asset.sha256, asset.byte_size, asset.content_type, asset.width, asset.height):
        raise ApiError(
            409, "EDITING_IMAGE_RESULT_CHANGED", "创意图原件与交付记录不一致。"
        )
    if stored.width * stored.height > settings.max_image_pixels:
        raise ApiError(
            422, "EDITING_IMAGE_RESULT_LIMIT", "图片像素总量超出剪辑素材限制。"
        )

    row = EditingMaterialRecord(
        id=str(uuid4()),
        request_id=str(body.request_id),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=str(project_id),
        kind="image",
        mime=stored.content_type,
        sha256=stored.sha256,
        bytes=stored.byte_size,
        width=stored.width,
        height=stored.height,
        label=label,
        description=description,
        source_job_id=body.job_id,
        source_asset_id=body.asset_id,
    )
    target = material_file(settings, row.id, row.mime)
    try:
        target.parent.mkdir(parents=True)
        with target.open("xb") as stream:
            stream.write(payload)
    except OSError:
        remove_candidate(target)
        raise
    return commit_material(session, row, target, identity)


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
