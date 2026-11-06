"""Private image/video avatar intake using the existing reviewed-template jobs."""

from __future__ import annotations

import hashlib
import json
import shutil
import warnings
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, File, Form, Request, UploadFile
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from .auth import SessionDependency, require_workspace_write
from .errors import ApiError
from .models import utc_now
from .video_generation import H3_PROMPT, job_response, process_generation, providers
from .video_generation_models import VideoAvatarRecord, VideoGenerationRecord
from .video_stage_timing import transition
from .video_studio_routes import VideoWorkspace
from .video_template_media import run_media, video_info

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}", tags=["video-avatars"]
)
CONSENT_VERSION = "avatar-v1"
IMAGE_BYTES = 10 * 1024 * 1024
VIDEO_BYTES = 50 * 1024 * 1024


def prepare_sample(source: Path, directory: Path, kind: str) -> Path:
    cover = directory / "cover.png"
    if kind == "image":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(source) as image:
                    if image.format not in {"JPEG", "PNG", "WEBP"}:
                        raise ValueError()
                    if min(image.size) < 256 or max(image.size) > 8192:
                        raise ValueError()
                    image.load()
                    normalized = ImageOps.exif_transpose(image).convert("RGB")
                    normalized.thumbnail((2048, 2048))
                    normalized.save(cover, format="PNG")
        except (OSError, ValueError, Image.DecompressionBombError, Warning):
            raise ApiError(
                422,
                "VIDEO_AVATAR_IMAGE_INVALID",
                "请上传清晰的 JPG、PNG 或 WebP 图片，边长为 256～8192 像素。",
            ) from None
        return cover
    info = video_info(source)
    if not 2 <= info["duration"] <= 120 or min(info["source_size"]) < 256:
        raise ApiError(
            422, "VIDEO_AVATAR_VIDEO_INVALID", "请上传 2～120 秒、画面清晰的出镜视频。"
        )
    target = directory / "template.mp4"
    run_media(
        [
            "-y",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "scale='min(1080,iw)':-2,fps=25,format=yuv420p",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-preset",
            "fast",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(target),
        ]
    )
    run_media(
        [
            "-y",
            "-protocol_whitelist",
            "file,pipe",
            "-ss",
            "0.2",
            "-i",
            str(target),
            "-frames:v",
            "1",
            "-vf",
            "scale=360:-2",
            str(cover),
        ]
    )
    return target


@router.post("/avatar-clones")
async def create_avatar(
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
    request_id: Annotated[UUID, Form()],
    name: Annotated[str, Form(min_length=1, max_length=30)],
    consent: Annotated[bool, Form()],
    consent_version: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    require_workspace_write(workspace)
    if not consent or consent_version != CONSENT_VERSION:
        raise ApiError(
            422, "VIDEO_AVATAR_CONSENT_REQUIRED", "请确认你拥有该形象的使用授权。"
        )
    settings = request.app.state.settings
    if not settings.video_providers_enabled:
        raise ApiError(503, "VIDEO_PROVIDER_DISABLED", "形象创建暂不可用。")
    clean_name = name.strip()
    if not clean_name:
        raise ApiError(422, "VIDEO_AVATAR_NAME_REQUIRED", "请填写形象名称。")
    suffix = Path(file.filename or "").suffix.lower()
    kind = "image" if suffix in {".jpg", ".jpeg", ".png", ".webp"} else "video"
    if kind == "video" and suffix not in {".mp4", ".mov", ".webm"}:
        raise ApiError(
            422, "VIDEO_AVATAR_TYPE_INVALID", "请选择图片或 MP4、MOV、WebM 视频。"
        )
    directory = settings.video_media_dir / "avatar-uploads" / str(uuid4())
    directory.mkdir(parents=True)
    source = directory / ("source" + suffix)
    digest = hashlib.sha256()
    size = 0
    retained = False
    try:
        with source.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > (IMAGE_BYTES if kind == "image" else VIDEO_BYTES):
                    raise ApiError(
                        413,
                        "VIDEO_AVATAR_TOO_LARGE",
                        "图片最大 10 MB，视频最大 50 MB。",
                    )
                digest.update(chunk)
                out.write(chunk)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "name": clean_name,
                    "kind": kind,
                    "sha256": digest.hexdigest(),
                    "consent_version": consent_version,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()

        def existing() -> VideoGenerationRecord | None:
            return session.scalar(
                select(VideoGenerationRecord).where(
                    VideoGenerationRecord.workspace_id == workspace.workspace_id,
                    VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
                    VideoGenerationRecord.request_id == str(request_id),
                )
            )

        def reconcile(row: VideoGenerationRecord) -> dict[str, Any]:
            if row.request_hash != fingerprint:
                raise ApiError(
                    409,
                    "VIDEO_REQUEST_REUSED",
                    "原提交的素材或名称不同，请先核对任务。",
                )
            return job_response(row)

        old = existing()
        if old:
            return reconcile(old)
        session.commit()
        sample = await run_in_threadpool(prepare_sample, source, directory, kind)
        avatar_id = "own-avatar-" + uuid4().hex
        job = VideoGenerationRecord(
            id=str(uuid4()),
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            avatar_id=avatar_id,
            request_id=str(request_id),
            request_hash=fingerprint,
            kind="h3_template",
            status="queued" if kind == "image" else "awaiting_review",
            stage="queued" if kind == "image" else "awaiting_review",
            details={
                "prompt": H3_PROMPT,
                "reference_path": str(directory / "cover.png"),
                "sample_kind": kind,
                "sample_sha256": digest.hexdigest(),
                "consent_version": consent_version,
                "consent_at": utc_now().isoformat(),
                "stage_history": transition(
                    [], "queued" if kind == "image" else "awaiting_review"
                ),
                **(
                    {"uploaded_video_path": str(sample), "result_path": str(sample)}
                    if kind == "video"
                    else {}
                ),
            },
        )
        session.add(
            VideoAvatarRecord(
                id=avatar_id,
                source="self_owned",
                name=clean_name,
                cover_path=str(directory / "cover.png"),
            )
        )
        session.flush()
        session.add(job)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            old = existing()
            if old:
                return reconcile(old)
            raise
        retained = True
        if kind == "image":
            background.add_task(
                process_generation,
                request.app.state.session_factory,
                settings,
                job.id,
                providers(request),
            )
        return job_response(job)
    finally:
        await file.close()
        if not retained:
            shutil.rmtree(directory)
