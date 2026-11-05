"""Owned voice uploads, durable enrollment, read-only recovery and cached previews."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

import imageio_ffmpeg
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .config import Settings
from .errors import ApiError
from .models import utc_now
from .video_cosyvoice import (
    CONSENT_VERSION,
    EMOTIONS,
    LANGUAGES,
    MODEL,
    PREVIEW_TEXT,
    CosyVoice,
    account_scope,
    ready,
)
from .video_studio_routes import VideoWorkspace
from .video_voice_models import VideoClonedVoiceRecord

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-voice-cloning"],
)


class CloneResponse(BaseModel):
    id: str
    name: str
    status: str
    preview_status: str
    preview_url: str | None
    error_code: str | None
    created_at: str
    sample_seconds: float | None


class CloneConfigResponse(BaseModel):
    available: bool
    max_bytes: int
    min_seconds: int
    max_seconds: int
    consent_version: str
    preview_text: str


def adapter(request: Request) -> CosyVoice:
    return getattr(request.app.state, "video_cosyvoice", None) or CosyVoice(
        request.app.state.settings
    )


def owned(
    session: Session, workspace: WorkspaceContext, voice_id: str
) -> VideoClonedVoiceRecord:
    row = session.scalar(
        select(VideoClonedVoiceRecord).where(
            VideoClonedVoiceRecord.id == voice_id,
            VideoClonedVoiceRecord.workspace_id == workspace.workspace_id,
            VideoClonedVoiceRecord.owner_user_id == workspace.principal.user_id,
        )
    )
    if not row:
        raise ApiError(404, "VIDEO_CLONE_NOT_FOUND", "未找到专属声音。")
    return row


def rows_for(
    session: Session, workspace: WorkspaceContext
) -> Sequence[VideoClonedVoiceRecord]:
    return session.scalars(
        select(VideoClonedVoiceRecord)
        .where(
            VideoClonedVoiceRecord.workspace_id == workspace.workspace_id,
            VideoClonedVoiceRecord.owner_user_id == workspace.principal.user_id,
        )
        .order_by(VideoClonedVoiceRecord.created_at.desc())
    ).all()


def response(row: VideoClonedVoiceRecord) -> CloneResponse:
    return CloneResponse(
        id=row.id,
        name=row.name,
        status=row.status,
        preview_status=row.preview_status,
        error_code=row.error_code,
        created_at=row.created_at.isoformat(),
        sample_seconds=row.details.get("sample_seconds"),
        preview_url=f"/api/v1/video-studio/workspaces/{row.workspace_id}/voice-clones/{row.id}/preview"
        if row.preview_status == "ready"
        else None,
    )


def catalog(
    settings: Settings, session: Session, workspace: WorkspaceContext
) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "name": row.name,
            "gender": "未知",
            "tag": "我的声音",
            "description": "本人录音复刻",
            "source": "own",
            "available": ready(settings)
            and row.status == "ready"
            and row.provider_workspace == account_scope(settings),
            "language": "中文",
            "emotions": list(EMOTIONS),
            "languages": LANGUAGES,
            "preview_url": response(row).preview_url,
        }
        for row in rows_for(session, workspace)
        if row.status == "ready"
    ]


def select_voice(
    settings: Settings,
    session: Session,
    workspace: WorkspaceContext,
    draft: dict[str, Any],
) -> dict[str, Any]:
    row = owned(session, workspace, draft["voiceId"])
    if not ready(settings):
        raise ApiError(503, "VIDEO_CLONE_NOT_CONFIGURED", "专属声音服务尚未配置。")
    if (
        row.status != "ready"
        or not row.provider_voice_id
        or row.provider_workspace != account_scope(settings)
    ):
        raise ApiError(409, "VIDEO_CLONE_NOT_READY", "声音尚未就绪，请先查询克隆状态。")
    emotion, language = draft.get("emotion", "自然"), draft.get("language", "auto")
    if emotion not in EMOTIONS or language not in LANGUAGES:
        raise ApiError(
            422, "VIDEO_VOICE_SETTING_INVALID", "请选择此声音支持的情绪与语言。"
        )
    instruction = EMOTIONS[emotion]
    if language == "Chinese,Yue":
        instruction += "请讲粤语。"
    return {
        "provider": "cosyvoice",
        "model": row.model,
        "voice_id": row.provider_voice_id,
        "voice_name": row.name,
        "clone_id": row.id,
        "provider_workspace": row.provider_workspace,
        "speed": draft["speed"],
        "emotion": emotion,
        "instruction": instruction,
        "language_boost": language,
    }


def reconcile(row: VideoClonedVoiceRecord, provider: CosyVoice) -> None:
    if not row.provider_voice_id:
        row.provider_voice_id = provider.find(row)
    if not row.provider_voice_id:
        # Absence in a list does NOT prove creation failed. Never resubmit.
        row.status = "unknown"
        row.error_code = "VIDEO_CLONE_OUTCOME_UNKNOWN"
        return
    data = provider.query(row.provider_voice_id)
    if data.get("target_model") != row.model:
        raise ApiError(
            502, "VIDEO_CLONE_MODEL_MISMATCH", "音色绑定模型不符，请联系管理员。"
        )
    row.status = {"OK": "ready", "DEPLOYING": "processing", "UNDEPLOYED": "failed"}.get(
        data.get("status") or "", "unknown"
    )
    row.error_code = "VIDEO_CLONE_REJECTED" if row.status == "failed" else None


def enroll(
    factory: sessionmaker[Session],
    settings: Settings,
    voice_id: str,
    provider: CosyVoice,
) -> None:
    with factory() as session:
        changed = session.execute(
            update(VideoClonedVoiceRecord)
            .where(
                VideoClonedVoiceRecord.id == voice_id,
                VideoClonedVoiceRecord.status == "queued",
            )
            .values(status="submitting")
        )
        session.commit()
        if cast(CursorResult[Any], changed).rowcount != 1:
            return
        row = session.get(VideoClonedVoiceRecord, voice_id)
        if row is None:
            return
        try:
            row.provider_voice_id = provider.create(row)
            row.status = "processing"
            session.commit()  # Save remote identity before any query.
            reconcile(row, provider)
        except ApiError as error:
            row.status = (
                "failed"
                if error.code == "VIDEO_PROVIDER_REJECTED" and not row.provider_voice_id
                else "unknown"
            )
            row.error_code = error.code
        except Exception:
            row.status, row.error_code = "unknown", "VIDEO_CLONE_OUTCOME_UNKNOWN"
        session.commit()


def make_preview(
    factory: sessionmaker[Session],
    settings: Settings,
    voice_id: str,
    provider: CosyVoice,
) -> None:
    with factory() as session:
        row = session.get(VideoClonedVoiceRecord, voice_id)
        if row is None:
            return
        path = settings.video_media_dir / "voice-clones" / row.id / "preview.mp3"
        try:
            if path.is_file():
                receipt = row.details.get("preview_billing") or {
                    "billing_status": "unreconciled",
                    "actual_cny": None,
                }
            else:
                receipt = provider.synthesize(
                    {
                        "voice_id": row.provider_voice_id,
                        "speed": 1,
                        "language_boost": "Chinese",
                    },
                    PREVIEW_TEXT,
                    path,
                )
            row.details = {**row.details, "preview_billing": receipt}
            row.preview_status = "ready"
            row.error_code = None
        except Exception as error:
            row.preview_status = "unknown"
            row.error_code = (
                error.code
                if isinstance(error, ApiError)
                else "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
            )
        session.commit()


@router.get("/voice-clone-config", response_model=CloneConfigResponse)
def clone_config(request: Request, workspace: VideoWorkspace) -> CloneConfigResponse:
    return CloneConfigResponse(
        available=ready(request.app.state.settings),
        max_bytes=10 * 1024 * 1024,
        min_seconds=5,
        max_seconds=60,
        consent_version=CONSENT_VERSION,
        preview_text=PREVIEW_TEXT,
    )


@router.get("/voice-clones", response_model=list[CloneResponse])
def list_clones(
    workspace: VideoWorkspace, session: SessionDependency
) -> list[CloneResponse]:
    return [response(row) for row in rows_for(session, workspace)]


@router.get("/voice-clones/{voice_id}", response_model=CloneResponse)
def clone_status(
    voice_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> CloneResponse:
    return response(owned(session, workspace, voice_id))


@router.post("/voice-clones", response_model=CloneResponse)
def create_clone(
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
    request_id: Annotated[UUID, Form()],
    name: Annotated[str, Form(min_length=1, max_length=30)],
    consent: Annotated[Literal["own-voice-2026-11-05"], Form()],
) -> CloneResponse:
    require_workspace_write(workspace)
    settings = request.app.state.settings
    if not ready(settings):
        raise ApiError(
            503, "VIDEO_CLONE_NOT_CONFIGURED", "专属声音服务尚未配置，请联系管理员。"
        )
    name = name.strip()
    if not name:
        raise ApiError(422, "VIDEO_CLONE_NAME_INVALID", "请输入声音名称。")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a"}:
        raise ApiError(
            422, "VIDEO_CLONE_AUDIO_INVALID", "请选择 MP3、WAV 或 M4A 录音。"
        )
    # Bounded read; the sample is never made public or sent via a user URL.
    data = file.file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise ApiError(413, "VIDEO_CLONE_AUDIO_TOO_LARGE", "请选择 10 MB 以内的录音。")
    digest = hashlib.sha256(data).hexdigest()
    fingerprint = hashlib.sha256(
        json.dumps([digest, name, consent]).encode()
    ).hexdigest()
    old = session.scalar(
        select(VideoClonedVoiceRecord).where(
            VideoClonedVoiceRecord.workspace_id == workspace.workspace_id,
            VideoClonedVoiceRecord.owner_user_id == workspace.principal.user_id,
            VideoClonedVoiceRecord.request_id == str(request_id),
        )
    )
    if old:
        if old.request_hash != fingerprint:
            raise ApiError(
                409, "VIDEO_REQUEST_REUSED", "此提交标识已用于另一份录音或名称。"
            )
        return response(old)
    # Reuse identical samples even after the caller loses its request ID.
    duplicate = session.scalar(
        select(VideoClonedVoiceRecord).where(
            VideoClonedVoiceRecord.workspace_id == workspace.workspace_id,
            VideoClonedVoiceRecord.owner_user_id == workspace.principal.user_id,
            VideoClonedVoiceRecord.sample_sha256 == digest,
        )
    )
    if duplicate:
        return response(duplicate)
    id = "cv-voice-" + uuid4().hex
    root = settings.video_media_dir / "voice-clones" / id
    root.mkdir(parents=True, exist_ok=False)
    source, target = root / ("source" + suffix), root / "sample.wav"
    source.write_bytes(data)
    try:
        # Decode locally, reject remote playlist protocols, bound output and duration.
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(source),
                "-t",
                "61",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "24000",
                "-c:a",
                "pcm_s16le",
                str(target),
            ],
            check=True,
            timeout=30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        with wave.open(str(target), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
        if not math.isfinite(seconds) or not 5 <= seconds <= 60:
            raise ValueError()
    except (subprocess.SubprocessError, OSError, ValueError, wave.Error):
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise ApiError(
            422,
            "VIDEO_CLONE_AUDIO_INVALID",
            "录音需可正常解码，时长 5～60 秒；推荐 10～20 秒清晰独白。",
        ) from None
    row = VideoClonedVoiceRecord(
        id=id,
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        request_id=str(request_id),
        request_hash=fingerprint,
        name=name,
        prefix="p" + uuid4().hex[:9],
        model=MODEL,
        provider_workspace=account_scope(settings),
        sample_path=str(target),
        sample_sha256=digest,
        consent_version=consent,
        consent_at=utc_now(),
        status="queued",
        preview_status="not_created",
        details={"sample_seconds": seconds},
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        source.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        old = session.scalar(
            select(VideoClonedVoiceRecord).where(
                VideoClonedVoiceRecord.workspace_id == workspace.workspace_id,
                VideoClonedVoiceRecord.owner_user_id == workspace.principal.user_id,
                VideoClonedVoiceRecord.request_id == str(request_id),
            )
        )
        if not old or old.request_hash != fingerprint:
            raise ApiError(
                409, "VIDEO_REQUEST_REUSED", "提交冲突，请查看原记录。"
            ) from None
        return response(old)
    background.add_task(
        enroll, request.app.state.session_factory, settings, row.id, adapter(request)
    )
    return response(row)


@router.post("/voice-clones/{voice_id}/refresh", response_model=CloneResponse)
def refresh_clone(
    voice_id: str,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> CloneResponse:
    require_workspace_write(workspace)
    row = owned(session, workspace, voice_id)
    if row.provider_workspace != account_scope(request.app.state.settings):
        raise ApiError(
            409, "VIDEO_CLONE_ACCOUNT_CHANGED", "声音服务账号已变化，请联系管理员。"
        )
    if row.status == "queued":
        # A worker that never acquired the queued record never sent a POST.
        # enroll() claims it atomically; concurrent recovery cannot create twice.
        background.add_task(
            enroll,
            request.app.state.session_factory,
            request.app.state.settings,
            row.id,
            adapter(request),
        )
    if row.status in {"processing", "submitting", "unknown", "ready"}:
        reconcile(row, adapter(request))  # Query only, including after process restart.
        session.commit()
    return response(row)


@router.post("/voice-clones/{voice_id}/preview", response_model=CloneResponse)
def prepare_preview(
    voice_id: str,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> CloneResponse:
    require_workspace_write(workspace)
    row = owned(session, workspace, voice_id)
    select_voice(
        request.app.state.settings,
        session,
        workspace,
        {"voiceId": voice_id, "speed": 1},
    )
    # Only the first explicit click submits. Unknown results cannot be resubmitted.
    path = (
        request.app.state.settings.video_media_dir
        / "voice-clones"
        / row.id
        / "preview.mp3"
    )
    if path.is_file() and row.preview_status != "ready":
        row.preview_status = "ready"
        session.commit()
    changed = session.execute(
        update(VideoClonedVoiceRecord)
        .where(
            VideoClonedVoiceRecord.id == row.id,
            VideoClonedVoiceRecord.preview_status == "not_created",
        )
        .values(preview_status="submitting")
    )
    session.commit()
    if cast(CursorResult[Any], changed).rowcount == 1:
        background.add_task(
            make_preview,
            request.app.state.session_factory,
            request.app.state.settings,
            row.id,
            adapter(request),
        )
    session.refresh(row)
    return response(row)


@router.get("/voice-clones/{voice_id}/preview")
def clone_preview(
    voice_id: str,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> FileResponse:
    row = owned(session, workspace, voice_id)
    path = (
        request.app.state.settings.video_media_dir
        / "voice-clones"
        / row.id
        / "preview.mp3"
    )
    if row.preview_status != "ready" or not path.is_file():
        raise ApiError(404, "VIDEO_VOICE_PREVIEW_PENDING", "请先生成一次试听。")
    return FileResponse(
        path, media_type="audio/mpeg", headers={"Cache-Control": "private, no-store"}
    )
