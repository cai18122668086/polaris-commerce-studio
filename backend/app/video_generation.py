"""Durable, single-submit video jobs. Unknown paid outcomes require reconciliation."""

from __future__ import annotations

import hashlib
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, File, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .config import Settings
from .errors import ApiError
from .models import utc_now
from .video_avatar_access import avatar_scope
from .video_avatar_catalog import public_avatar_gender
from .video_cosyvoice import CosyVoice
from .video_generation_media import (
    MODEL_REGISTRATION_STAGES,
    prepare_lipsync_media,
    register_model,
    set_stage,
)
from .video_generation_models import (
    VideoAudioRecord,
    VideoAvatarRecord,
    VideoGenerationRecord,
)
from .video_generation_runtime import (
    VideoRunLease,
    VideoRunLost,
    acquire_run,
    guard_run,
    owner_can_run,
    unconfirmed_paid_submission,
)
from .video_lipsync import run_lipsync
from .video_providers import VideoProviders, safe_media_url
from .video_stage_timing import transition
from .video_studio_models import VideoProjectRecord
from .video_studio_routes import VideoWorkspace, append_version, scope
from .video_studio_schemas import StrictVideoModel
from .video_tts import synthesize
from .video_voice_catalog import VOICES, official_voices, preview_path, select_tao_voice
from .video_voice_cloning import catalog as cloned_voice_catalog
from .video_voice_cloning import select_voice as select_cloned_voice

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}", tags=["video-generation"]
)
OWNED_IMAGE = (
    Path(__file__).resolve().parents[2]
    / "assets/video-studio/owned/presenter-female-v1.png"
)
H3_PROMPT = (
    "以 @图1 为唯一人物、服装、背景和起始姿态参考，生成15秒真人感强、安定从容的"
    "口播数字人动作底片。竖屏腰部以上，双手完整可见，固定机位，曝光光线稳定，保留"
    "真实皮肤细节和人物一致性。身体直立放松，头部、躯干与胸肩位置稳定，肩线高度几乎"
    "固定，身体只有几乎不可察觉的缓慢微动。不耸肩、不挺胸、不深吸气、不急促喘气、"
    "不前后摇晃，不用胸肩带动手势。动作集中于前臂和手腕，每次仅一组低幅度手势，"
    "手肘靠近身体，动作之间有自然停顿。0至3秒保持参考图中性姿态；3至6秒右手在"
    "腰腹前小幅掌心向上解释，躯干不动；6至9秒右手缓慢回位并停顿；9至11秒左手"
    "做一次轻微补充手势并回位；11至15秒双手、头部、视线、肩线回到与开头一致的"
    "中性位置并安静保持，方便正向首尾衔接。表情平和，口周清晰放松，嘴唇闭合或轻微"
    "张开，不主动连续说话，不张嘴喘气，不大笑，便于后续音频驱动。手不遮脸，不点头"
    "晃头，不走动、不转身、不运镜、不切镜，无配音、无文字水印。"
)


class AvatarResponse(StrictVideoModel):
    id: str
    name: str
    source: Literal["quanyu_public", "self_owned"]
    gender: str
    tag: str
    cover_url: str
    preview_url: str | None = None
    ready: bool


class GenerationRequest(StrictVideoModel):
    request_id: UUID
    kind: Literal["lipsync", "h3_template"]
    avatar_id: str = Field(max_length=80)
    project_id: UUID | None = None
    expected_revision: int | None = Field(default=None, ge=1)
    audio_id: UUID | None = None
    prompt: str = Field(default=H3_PROMPT, min_length=20, max_length=6000)


def providers(request: Request) -> VideoProviders:
    return getattr(request.app.state, "video_providers", None) or VideoProviders(
        request.app.state.settings
    )


def own_job(
    session: Session, workspace: WorkspaceContext, job_id: str | UUID
) -> VideoGenerationRecord:
    row = session.scalar(
        select(VideoGenerationRecord).where(
            VideoGenerationRecord.id == str(job_id),
            VideoGenerationRecord.workspace_id == workspace.workspace_id,
            VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
        )
    )
    if row is None:
        raise ApiError(404, "VIDEO_TASK_NOT_FOUND", "未找到任务。")
    return row


RESUMABLE_STAGES = {
    "downloading_video",
    "downloading_template",
    "uploading_template",
    "uploading_audio",
    "uploading_reference",
    "tts_generated",
    "uploading_tts_audio",
    "downloading_audio",
    "measuring_audio",
    "resolving_source",
    "downloading_source",
    "measuring_source",
    "preparing_forward_template",
    "uploading_forward_template",
    "backup_avatar_preparing",
}


def can_resume(row: VideoGenerationRecord) -> bool:
    return (
        row.status == "awaiting_resume"
        or (row.status == "failed" and row.stage in RESUMABLE_STAGES)
        or (row.status == "unknown" and row.stage in MODEL_REGISTRATION_STAGES)
    )


def job_response(row: VideoGenerationRecord) -> dict[str, Any]:
    base = (
        f"/api/v1/video-studio/workspaces/{row.workspace_id}/generation-tasks/{row.id}"
    )
    return {
        "id": row.id,
        "request_id": row.request_id,
        "kind": row.kind,
        "avatar_id": row.avatar_id,
        "project_id": row.project_id,
        "confirmed_version_id": row.confirmed_version_id,
        "status": row.status,
        "stage": row.stage,
        "error_code": row.error_code,
        "can_resume": can_resume(row),
        "created_at": (
            row.created_at.replace(tzinfo=UTC)
            if row.created_at.tzinfo is None
            else row.created_at
        ).isoformat(),
        "video_url": base + "/video"
        if row.status in {"completed", "awaiting_review"}
        else None,
        "audio_url": base + "/audio" if row.details.get("audio_url") else None,
        "snapshot": row.details.get("snapshot"),
        "audio_duration_seconds": row.details.get("audio_duration_seconds"),
        "lipsync_routing": {
            key: value
            for key, value in (row.details.get("lipsync_routing") or {}).items()
            if key
            in {
                "selected_provider",
                "switch_reason",
                "primary_status",
                "backup_status",
                "long_wait",
            }
        },
        "template_preparation": row.details.get("template_preparation"),
        "stage_history": row.details.get("stage_history", []),
        "tts": {"voice_name": (row.details.get("tts") or {}).get("voice_name")},
        "handoff_url": base + "/handoff"
        if row.kind == "lipsync" and row.status == "completed"
        else None,
    }


def provider_task_id(job: VideoGenerationRecord) -> str:
    if not job.provider_task_id:
        raise ApiError(
            502, "VIDEO_PROVIDER_RESPONSE_INVALID", "任务标识尚未确认，请查询原任务。"
        )
    return job.provider_task_id


def process_generation(
    factory: sessionmaker[Session],
    settings: Settings,
    job_id: str | UUID,
    provider: VideoProviders,
    *,
    lease: VideoRunLease | None = None,
) -> None:
    lease = lease or acquire_run(factory, settings, str(job_id))
    if lease is None:
        return
    with lease:
        try:
            _process_generation(factory, settings, job_id, provider, lease)
        except VideoRunLost:
            return


def _process_generation(
    factory: sessionmaker[Session],
    settings: Settings,
    job_id: str | UUID,
    provider: VideoProviders,
    lease: VideoRunLease,
) -> None:
    with factory() as session:
        session.info["video_run_lease"] = lease
        guard_run(session)
        changed = session.execute(
            update(VideoGenerationRecord)
            .where(
                VideoGenerationRecord.id == job_id,
                VideoGenerationRecord.status == "queued",
            )
            .values(status="running", error_code=None)
        )
        session.commit()
        if cast(CursorResult[Any], changed).rowcount != 1:
            return
        job = session.get(VideoGenerationRecord, job_id)
        if job is None:
            return
        session.commit()
        set_stage(session, job, job.stage)
        try:
            if not owner_can_run(session, job):
                raise ApiError(
                    403,
                    "VIDEO_RECOVERY_ACCESS_REVOKED",
                    "原任务权限已失效，已停止继续生成。",
                )
            if unconfirmed_paid_submission(job, settings):
                raise ApiError(
                    502,
                    "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                    "付费提交结果尚未确认，已保留原任务，禁止重复提交。",
                )
            if job.kind == "h3_template":
                local = (
                    Path(job.details["uploaded_video_path"])
                    if job.details.get("uploaded_video_path")
                    else settings.video_media_dir / "jobs" / job.id / "template.mp4"
                )
                if not job.details.get("uploaded_video_path"):
                    if not job.provider_task_id:
                        if not job.details.get("reference_url"):
                            set_stage(session, job, "uploading_reference")
                            ref = provider.upload(
                                Path(
                                    job.details.get("reference_path", str(OWNED_IMAGE))
                                ),
                                "image/png",
                                "digital_human_model",
                            )
                            set_stage(
                                session, job, "reference_ready", reference_url=ref
                            )
                        set_stage(session, job, "h3_submitting")
                        data = provider.request(
                            "wuye",
                            "POST",
                            "/v1/videos",
                            json={
                                "model": "Minimax-H3-768p-913",
                                "prompt": job.details["prompt"],
                                "duration": 15,
                                "ratio": "9:16",
                                "resolution": "768p",
                                "referenceImages": [job.details["reference_url"]],
                            },
                        )
                        if not data.get("id"):
                            raise ApiError(
                                502,
                                "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                                "生成结果未能确认。",
                            )
                        job.provider_task_id = data["id"]
                        set_stage(session, job, "h3_generating")
                    if not poll_until_complete(session, job, provider, "wuye"):
                        return
                    if not local.exists():
                        set_stage(session, job, "downloading_template")
                        provider.download(
                            "https://www.wuyeai.cn/v1/videos/"
                            + provider_task_id(job)
                            + "/content",
                            local,
                            vendor="wuye",
                        )
                if not job.details.get("review_approved"):
                    set_stage(session, job, "awaiting_review", result_path=str(local))
                    job.status = "awaiting_review"
                    guard_run(session)
                    session.commit()
                    return
                if not job.details.get("template_url"):
                    set_stage(session, job, "uploading_template")
                    link = provider.upload(local, "video/mp4", "digital_human_model")
                    set_stage(session, job, "template_ready", template_url=link)
                if not job.details.get("model_id"):
                    data = register_model(
                        session,
                        job,
                        provider,
                        stage="model_submitting",
                        name="极光原创-" + job.id,
                        video_url=job.details["template_url"],
                    )
                    model_id = (data.get("model") or {}).get("id")
                    if not model_id:
                        raise ApiError(
                            502,
                            "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                            "形象登记结果未确认。",
                        )
                    set_stage(
                        session,
                        job,
                        "completed",
                        model_id=model_id,
                        result_path=str(local),
                    )
            else:
                if not job.details.get("audio_url"):
                    if job.details.get("audio_id"):
                        audio = session.get(VideoAudioRecord, job.details["audio_id"])
                        if (
                            audio is None
                            or audio.owner_user_id != job.owner_user_id
                            or audio.workspace_id != job.workspace_id
                        ):
                            raise ApiError(
                                404, "VIDEO_AUDIO_NOT_FOUND", "未找到任务音频。"
                            )
                        path, mime = Path(audio.path), audio.mime
                        session.commit()
                        set_stage(session, job, "uploading_audio")
                        link = provider.upload(path, mime, "digital_human_audio")
                        set_stage(session, job, "audio_ready", audio_url=link)
                    elif job.details.get("tts", {}).get("provider") in {
                        "tao",
                        "cosyvoice",
                    }:
                        local = (
                            settings.video_media_dir / "jobs" / job.id / "narration.mp3"
                        )
                        if not job.details.get("tts_local_path"):
                            # A persisted file left by an interrupted DB checkpoint
                            # is reconciled locally without another paid submission.
                            if not local.exists():
                                set_stage(session, job, "tts_submitting")
                                if job.details["tts"]["provider"] == "cosyvoice":
                                    receipt = CosyVoice(
                                        settings, getattr(provider, "transport", None)
                                    ).synthesize(
                                        job.details["tts"],
                                        job.details["snapshot"]["draft"]["text"],
                                        local,
                                    )
                                else:
                                    receipt = synthesize(
                                        settings,
                                        job.details["tts"],
                                        job.details["snapshot"]["draft"]["text"],
                                        local,
                                        getattr(provider, "transport", None),
                                    )
                            else:
                                receipt = {
                                    "provider": job.details["tts"]["provider"],
                                    "billing_status": "unreconciled",
                                    "actual_cny": None,
                                }
                            set_stage(
                                session,
                                job,
                                "tts_generated",
                                tts_local_path=str(local),
                                billing=[receipt],
                            )
                        set_stage(session, job, "uploading_tts_audio")
                        link = provider.upload(
                            local, "audio/mpeg", "digital_human_audio"
                        )
                        set_stage(session, job, "audio_ready", audio_url=link)
                    else:
                        draft = job.details["snapshot"]["draft"]
                        set_stage(session, job, "tts_submitting")
                        data = provider.request(
                            "quanyu",
                            "POST",
                            "/api/tts/generate",
                            json={
                                "text": draft["text"],
                                "cloud_voice_id": job.details["voice_id"],
                                "speed": draft["speed"],
                                "volume": 1.0,
                                "subtitle_enable": True,
                                "subtitle_type": "sentence",
                            },
                        )
                        link = safe_media_url(data.get("audio_url", ""))
                        set_stage(
                            session,
                            job,
                            "audio_ready",
                            audio_url=link,
                            tts_record_id=data.get("record_id"),
                            subtitles=data.get("subtitle_data"),
                            billing=[data.get("billing", {})],
                        )
                if not job.provider_task_id:
                    prepare_lipsync_media(session, job, settings, provider)
                if not run_lipsync(session, job, settings, provider):
                    return
                local = settings.video_media_dir / "jobs" / job.id / "result.mp4"
                if not local.exists():
                    set_stage(session, job, "downloading_video")
                    routing = job.details.get("lipsync_routing") or {}
                    if routing.get("selected_provider") == "skyhuman":
                        provider.download(routing["result_url"], local)
                    else:
                        provider.download(
                            "https://quanyu.sowa.chat/api/download/"
                            + provider_task_id(job),
                            local,
                            vendor="quanyu",
                        )
                set_stage(session, job, "completed", result_path=str(local))
            job.status = "completed"
            guard_run(session)
            session.commit()
        except VideoRunLost:
            session.rollback()
            return
        except Exception as error:
            session.rollback()
            job = session.get(VideoGenerationRecord, job_id)
            if job is None:
                return
            try:
                guard_run(session)
            except VideoRunLost:
                session.rollback()
                return
            code = (
                error.code if isinstance(error, ApiError) else "VIDEO_PROCESSING_FAILED"
            )
            # POST may have been accepted even if the response was lost. Never
            # let a restart/retry automatically submit another billable call.
            submitting = job.stage in {
                "h3_submitting",
                "model_submitting",
                "tts_submitting",
                "lipsync_submitting",
                "forward_model_submitting",
                "backup_lipsync_submitting",
            }
            job.status = (
                "awaiting_resume"
                if code == "VIDEO_MODEL_REGISTRATION_PENDING"
                else "unknown"
                if code == "VIDEO_PROVIDER_OUTCOME_UNKNOWN"
                or submitting
                and code != "VIDEO_PROVIDER_REJECTED"
                else "failed"
            )
            job.error_code = code
            job.details = {
                **job.details,
                "stage_history": transition(
                    job.details.get("stage_history"),
                    job.stage,
                    finish=True,
                    outcome=job.status,
                ),
            }
            session.commit()


def poll_until_complete(
    session: Session, job: VideoGenerationRecord, provider: VideoProviders, vendor: str
) -> bool:
    for _ in range(180):
        guard_run(session)
        job.updated_at = utc_now()
        session.commit()
        path = (
            "/v1/videos/" + provider_task_id(job)
            if vendor == "wuye"
            else "/api/status/" + provider_task_id(job)
        )
        try:
            data = provider.request(vendor, "GET", path)
        except ApiError:
            time.sleep(5)
            continue
        status = str(data.get("status", "")).lower()
        if status in {"completed", "success", "succeeded"}:
            set_stage(
                session,
                job,
                "provider_completed",
                provider_result=data.get("result", {}),
            )
            return True
        if status in {"failed", "error", "cancelled"}:
            raise ApiError(502, "VIDEO_PROVIDER_TASK_FAILED", "供应商任务失败。")
        time.sleep(5)
    job.status = "awaiting_resume"
    guard_run(session)
    job.details = {
        **job.details,
        "stage_history": transition(
            job.details.get("stage_history"),
            job.stage,
            finish=True,
            outcome="awaiting_resume",
        ),
    }
    session.commit()
    return False


@router.get("/avatars", response_model=list[AvatarResponse])
def avatars(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    refresh: bool = False,
) -> list[AvatarResponse]:
    existing = session.scalars(
        select(VideoAvatarRecord).where(VideoAvatarRecord.source == "quanyu_public")
    ).all()
    if not existing or refresh:
        session.commit()
        models = providers(request).models()
        for model in models:
            if (
                not model.get("is_public")
                or not model.get("is_active", True)
                or model.get("model_type") != "video"
            ):
                continue
            url = safe_media_url(model["video_url"])
            id = "qy-model-" + str(model["id"])
            row = session.get(VideoAvatarRecord, id) or VideoAvatarRecord(
                id=id,
                source="quanyu_public",
                name=model["model_name"],
                provider_model_id=model["id"],
            )
            row.name, row.video_url, row.active = model["model_name"], url, True
            session.add(row)
        session.commit()
    if (
        OWNED_IMAGE.exists()
        and session.get(VideoAvatarRecord, "self-presenter-female-v1") is None
    ):
        session.add(
            VideoAvatarRecord(
                id="self-presenter-female-v1",
                source="self_owned",
                name="清禾·原创形象",
                gender="女",
                cover_path=str(OWNED_IMAGE),
            )
        )
        session.commit()
    rows = session.scalars(
        select(VideoAvatarRecord)
        .where(VideoAvatarRecord.active.is_(True), avatar_scope(workspace))
        .order_by(VideoAvatarRecord.source, VideoAvatarRecord.name)
    ).all()
    result = []
    for row in rows:
        owned = (
            session.scalar(
                select(VideoGenerationRecord)
                .where(
                    VideoGenerationRecord.avatar_id == row.id,
                    VideoGenerationRecord.kind == "h3_template",
                    VideoGenerationRecord.status == "completed",
                    VideoGenerationRecord.workspace_id == workspace.workspace_id,
                    VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
                )
                .order_by(VideoGenerationRecord.created_at.desc())
            )
            if row.source == "self_owned"
            else None
        )
        root = (
            f"/api/v1/video-studio/workspaces/{workspace.workspace_id}/avatars/{row.id}"
        )
        result.append(
            AvatarResponse(
                id=row.id,
                name=row.name,
                source=cast(Literal["quanyu_public", "self_owned"], row.source),
                gender=public_avatar_gender(row.provider_model_id, row.name, row.gender)
                if row.source == "quanyu_public"
                else row.gender,
                tag="公共数字人"
                if row.source == "quanyu_public"
                else "我的形象"
                if row.id.startswith("own-avatar-")
                else "极光原创",
                cover_url=root + "/cover",
                preview_url=root + "/preview" if row.video_url or owned else None,
                ready=bool(row.provider_model_id or owned),
            )
        )
    return result


@router.get("/voices")
def voices(
    request: Request, workspace: VideoWorkspace, session: SessionDependency
) -> list[dict[str, Any]]:
    current = [
        {
            "id": "qy-voice-" + str(v["id"]),
            "name": v.get("name") or v.get("voice_name"),
            "gender": "男" if "男" in (v.get("name") or "") else "女",
            "tag": "公共音色",
            "description": "系统声音",
            "available": True,
            "emotions": ["自然"],
            "languages": {"auto": "跟随音色原始语言"},
            "preview_url": None,
        }
        for v in providers(request).voices()
    ]
    root = f"/api/v1/video-studio/workspaces/{workspace.workspace_id}"
    result = (
        current
        + official_voices(request.app.state.settings, root)
        + cloned_voice_catalog(request.app.state.settings, session, workspace)
    )
    return [
        {key: value for key, value in voice.items() if key != "provider"}
        for voice in result
    ]


@router.get("/voices/{voice_id}/preview")
def voice_preview(
    voice_id: str, request: Request, workspace: VideoWorkspace
) -> FileResponse:
    if voice_id not in VOICES:
        raise ApiError(404, "VIDEO_VOICE_INVALID", "未找到音色。")
    path = preview_path(request.app.state.settings, voice_id)
    if not path.is_file():
        raise ApiError(404, "VIDEO_VOICE_PREVIEW_PENDING", "此音色试听尚未准备。")
    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/generation-prices")
def prices(request: Request, workspace: VideoWorkspace) -> dict[str, bool]:
    # Upstream procurement costs are internal accounting, not customer pricing.
    # Keep the legacy path compatible without calling a supplier price API.
    return {"pricing_available": False}


@router.get("/avatars/{avatar_id}/{kind}")
def avatar_media(
    avatar_id: str,
    kind: Literal["cover", "preview"],
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> FileResponse:
    import imageio_ffmpeg

    row = session.scalar(
        select(VideoAvatarRecord).where(
            VideoAvatarRecord.id == avatar_id, avatar_scope(workspace)
        )
    )
    if not row or not row.active:
        raise ApiError(404, "VIDEO_AVATAR_NOT_FOUND", "未找到形象。")
    if kind == "cover" and row.cover_path:
        return FileResponse(
            row.cover_path,
            media_type="image/png",
            headers={"Cache-Control": "private, no-store"},
        )
    if row.source == "self_owned" and not row.video_url:
        job = session.scalar(
            select(VideoGenerationRecord)
            .where(
                VideoGenerationRecord.avatar_id == row.id,
                VideoGenerationRecord.workspace_id == workspace.workspace_id,
                VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
                VideoGenerationRecord.status == "completed",
                VideoGenerationRecord.kind == "h3_template",
            )
            .order_by(VideoGenerationRecord.created_at.desc())
        )
        if not job:
            raise ApiError(404, "VIDEO_TEMPLATE_NOT_READY", "动作模板尚未生成。")
        return FileResponse(job.details["result_path"], media_type="video/mp4")
    url = safe_media_url(row.video_url or "")
    session.commit()
    root = request.app.state.settings.video_media_dir / "public"
    root.mkdir(parents=True, exist_ok=True)
    video = root / (avatar_id + ".mp4")
    if not video.exists():
        providers(request).download(url, video)
    if kind == "cover":
        target = root / (avatar_id + ".jpg")
        if not target.exists():
            temporary = root / (avatar_id + "-" + str(uuid4()) + ".jpg")
            try:
                subprocess.run(
                    [
                        imageio_ffmpeg.get_ffmpeg_exe(),
                        "-nostdin",
                        "-y",
                        "-protocol_whitelist",
                        "file,pipe",
                        "-ss",
                        "0.2",
                        "-i",
                        str(video),
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=360:-2",
                        str(temporary),
                    ],
                    check=True,
                    timeout=35,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                temporary.replace(target)
            except (subprocess.SubprocessError, OSError):
                temporary.unlink(missing_ok=True)
                raise ApiError(
                    502, "VIDEO_COVER_FAILED", "形象封面暂不可用。"
                ) from None
        return FileResponse(target, media_type="image/jpeg")
    return FileResponse(video, media_type="video/mp4")


@router.post("/audio-files")
async def upload_audio(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    from mutagen import File as AudioMetadata

    require_workspace_write(workspace)
    id = str(uuid4())
    suffix = Path(file.filename or "audio").suffix.lower()
    if suffix not in {".mp3", ".wav", ".m4a"}:
        raise ApiError(422, "VIDEO_AUDIO_TYPE_INVALID", "请选择 MP3、WAV 或 M4A 音频。")
    target = request.app.state.settings.video_media_dir / "audio" / (id + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    with target.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > 50 * 1024 * 1024:
                target.unlink(missing_ok=True)
                raise ApiError(
                    413, "VIDEO_AUDIO_TOO_LARGE", "请选择 50 MB 以内的音频。"
                )
            out.write(chunk)
    try:
        metadata = AudioMetadata(target)
        if metadata is None or metadata.info.length <= 0:
            raise ValueError()
    except Exception:
        target.unlink(missing_ok=True)
        raise ApiError(422, "VIDEO_AUDIO_TYPE_INVALID", "音频文件无法解析。") from None
    mime = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}[suffix]
    session.add(
        VideoAudioRecord(
            id=id,
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            filename=(file.filename or "audio")[:255],
            path=str(target),
            mime=mime,
        )
    )
    session.commit()
    return {"id": id, "name": file.filename, "duration": metadata.info.length}


@router.post("/generation-tasks")
def submit_generation(
    body: GenerationRequest,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    old = session.scalar(
        select(VideoGenerationRecord).where(
            VideoGenerationRecord.workspace_id == workspace.workspace_id,
            VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
            VideoGenerationRecord.request_id == str(body.request_id),
        )
    )
    if old:
        if old.request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求标识已用于其他内容。")
        return job_response(old)
    if not request.app.state.settings.video_providers_enabled:
        raise ApiError(503, "VIDEO_PROVIDER_DISABLED", "视频服务尚未配置。")
    avatar = session.scalar(
        select(VideoAvatarRecord).where(
            VideoAvatarRecord.id == body.avatar_id, avatar_scope(workspace)
        )
    )
    if not avatar or not avatar.active:
        raise ApiError(404, "VIDEO_AVATAR_NOT_FOUND", "请先选择有效形象。")
    details: dict[str, Any] = {}
    version = None
    if body.kind == "h3_template":
        if avatar.source != "self_owned":
            raise ApiError(
                422,
                "VIDEO_PUBLIC_AVATAR_NO_H3",
                "公共数字人直接使用，无需生成 H3 模板。",
            )
        active = session.scalar(
            select(VideoGenerationRecord).where(
                VideoGenerationRecord.workspace_id == workspace.workspace_id,
                VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
                VideoGenerationRecord.avatar_id == avatar.id,
                VideoGenerationRecord.kind == "h3_template",
                VideoGenerationRecord.status.in_(
                    [
                        "queued",
                        "running",
                        "awaiting_resume",
                        "awaiting_review",
                        "unknown",
                    ]
                ),
            )
        )
        if active:
            raise ApiError(
                409,
                "VIDEO_TEMPLATE_ALREADY_PROCESSING",
                "已有动作模板任务，请先查看或验收原任务。",
            )
        details["prompt"] = body.prompt
        details["reference_path"] = avatar.cover_path or str(OWNED_IMAGE)
        details["h3_model"] = "Minimax-H3-768p-913"
    else:
        project = session.scalar(
            select(VideoProjectRecord)
            .where(VideoProjectRecord.id == str(body.project_id), *scope(workspace))
            .with_for_update()
        )
        if not project:
            raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
        if project.revision != body.expected_revision:
            raise ApiError(
                409, "VIDEO_REVISION_CONFLICT", "项目已变化，请重新载入后确认。"
            )
        details["snapshot"] = project.content
        model_id = avatar.provider_model_id
        source_video = {"video_url": avatar.video_url} if avatar.video_url else None
        if avatar.source == "self_owned":
            template = session.scalar(
                select(VideoGenerationRecord)
                .where(
                    VideoGenerationRecord.avatar_id == avatar.id,
                    VideoGenerationRecord.workspace_id == workspace.workspace_id,
                    VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
                    VideoGenerationRecord.kind == "h3_template",
                    VideoGenerationRecord.status == "completed",
                )
                .order_by(VideoGenerationRecord.created_at.desc())
            )
            model_id = (
                template.details.get("model_id")
                if template
                else avatar.provider_model_id
            )
            if template:
                source_video = {"local_path": template.details["result_path"]}
        if not model_id:
            raise ApiError(
                409, "VIDEO_TEMPLATE_NOT_READY", "请先生成原创形象的动作模板。"
            )
        details["model_id"] = model_id
        if not source_video:
            raise ApiError(
                409, "VIDEO_TEMPLATE_NOT_READY", "请先准备可读取的动作模板。"
            )
        details["source_video"] = source_video
        draft = project.content["draft"]
        if draft["avatarId"] != body.avatar_id:
            raise ApiError(
                409, "VIDEO_AVATAR_CHANGED", "形象已变化，请重新保存并确认。"
            )
        if draft["drive"] == "audio":
            audio = session.get(
                VideoAudioRecord, str(body.audio_id or draft.get("audioAssetId"))
            )
            if (
                not audio
                or audio.workspace_id != workspace.workspace_id
                or audio.owner_user_id != workspace.principal.user_id
            ):
                raise ApiError(404, "VIDEO_AUDIO_NOT_FOUND", "请先上传有效音频。")
            details["audio_id"] = audio.id
        else:
            if not draft["text"].strip():
                raise ApiError(422, "VIDEO_SCRIPT_EMPTY", "请输入文案。")
            if draft["voiceId"] in VOICES:
                details["tts"] = select_tao_voice(request.app.state.settings, draft)
            elif draft["voiceId"].startswith("cv-voice-"):
                details["tts"] = select_cloned_voice(
                    request.app.state.settings, session, workspace, draft
                )
            else:
                voice_id = draft["voiceId"].removeprefix("qy-voice-")
                session.commit()
                if voice_id not in {str(v["id"]) for v in providers(request).voices()}:
                    raise ApiError(422, "VIDEO_VOICE_INVALID", "请选择正式公共音色。")
                if (
                    draft.get("emotion", "自然") != "自然"
                    or draft.get("language", "auto") != "auto"
                ):
                    raise ApiError(
                        422,
                        "VIDEO_VOICE_SETTING_INVALID",
                        "此公共音色仅支持原始情绪与语言。",
                    )
                details["voice_id"] = voice_id
                details["tts"] = {
                    "provider": "quanyu",
                    "voice_id": voice_id,
                    "speed": draft["speed"],
                    "emotion": None,
                    "language_boost": None,
                }
        version = append_version(session, project.id, project.content, "confirmed")
    row = VideoGenerationRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=str(body.project_id) if body.kind == "lipsync" else None,
        confirmed_version_id=version.id if version else None,
        avatar_id=body.avatar_id,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        kind=body.kind,
        status="queued",
        details={**details, "stage_history": transition([], "queued")},
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        old = session.scalar(
            select(VideoGenerationRecord).where(
                VideoGenerationRecord.workspace_id == workspace.workspace_id,
                VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
                VideoGenerationRecord.request_id == str(body.request_id),
            )
        )
        if not old or old.request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求冲突。") from None
        return job_response(old)
    background.add_task(
        process_generation,
        request.app.state.session_factory,
        request.app.state.settings,
        row.id,
        providers(request),
    )
    return job_response(row)


@router.get("/audio-files/{audio_id}")
def stored_audio(
    audio_id: UUID, workspace: VideoWorkspace, session: SessionDependency
) -> FileResponse:
    row = session.get(VideoAudioRecord, str(audio_id))
    if (
        not row
        or row.workspace_id != workspace.workspace_id
        or row.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "VIDEO_AUDIO_NOT_FOUND", "未找到音频。")
    return FileResponse(row.path, media_type=row.mime)


@router.get("/generation-tasks")
def generation_tasks(
    workspace: VideoWorkspace, session: SessionDependency
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(VideoGenerationRecord)
        .where(
            VideoGenerationRecord.workspace_id == workspace.workspace_id,
            VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
        )
        .order_by(VideoGenerationRecord.created_at.desc())
        .limit(100)
    ).all()
    for row in rows:
        stamp = (
            row.updated_at.replace(tzinfo=UTC)
            if row.updated_at.tzinfo is None
            else row.updated_at
        )
        if (
            row.status == "running"
            # Downloads may use three 180-second GET attempts. Do not expire
            # the local worker's lease while those bounded attempts are active.
            and (datetime.now(UTC) - stamp).total_seconds() > 900
        ):
            row.status = (
                "unknown"
                if row.stage
                in {
                    "h3_submitting",
                    "model_submitting",
                    "tts_submitting",
                    "lipsync_submitting",
                    "forward_model_submitting",
                    "backup_lipsync_submitting",
                }
                else "awaiting_resume"
            )
    session.commit()
    return [job_response(row) for row in rows]


@router.post("/generation-tasks/{job_id}/approve-template")
def approve_template(
    job_id: UUID,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    row = own_job(session, workspace, job_id)
    if row.details.get("review_approved"):
        return job_response(row)
    if row.kind != "h3_template" or row.status != "awaiting_review":
        raise ApiError(
            409, "VIDEO_TEMPLATE_NOT_REVIEWABLE", "请先等待动作底片生成并预览确认。"
        )
    changed = session.execute(
        update(VideoGenerationRecord)
        .where(
            VideoGenerationRecord.id == row.id,
            VideoGenerationRecord.status == "awaiting_review",
        )
        .values(details={**row.details, "review_approved": True}, status="queued")
    )
    session.commit()
    session.refresh(row)
    if cast(CursorResult[Any], changed).rowcount != 1:
        return job_response(row)
    background.add_task(
        process_generation,
        request.app.state.session_factory,
        request.app.state.settings,
        row.id,
        providers(request),
    )
    return job_response(row)


@router.post("/generation-tasks/{job_id}/reject-template")
def reject_template(
    job_id: UUID, workspace: VideoWorkspace, session: SessionDependency
) -> dict[str, Any]:
    require_workspace_write(workspace)
    row = own_job(session, workspace, job_id)
    if row.kind != "h3_template" or row.status != "awaiting_review":
        raise ApiError(409, "VIDEO_TEMPLATE_NOT_REVIEWABLE", "当前任务不可验收。")
    session.execute(
        update(VideoGenerationRecord)
        .where(
            VideoGenerationRecord.id == row.id,
            VideoGenerationRecord.status == "awaiting_review",
        )
        .values(status="rejected", stage="review_rejected")
    )
    session.commit()
    session.refresh(row)
    return job_response(row)


@router.post("/generation-tasks/{job_id}/resume")
def resume_job(
    job_id: UUID,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    row = own_job(session, workspace, job_id)
    if not can_resume(row):
        raise ApiError(
            409, "VIDEO_TASK_NOT_RESUMABLE", "任务当前不可继续，请保留原任务查询。"
        )
    changed = session.execute(
        update(VideoGenerationRecord)
        .where(
            VideoGenerationRecord.id == row.id,
            VideoGenerationRecord.status == row.status,
        )
        .values(status="queued")
    )
    session.commit()
    session.refresh(row)
    if cast(CursorResult[Any], changed).rowcount != 1:
        return job_response(row)
    background.add_task(
        process_generation,
        request.app.state.session_factory,
        request.app.state.settings,
        row.id,
        providers(request),
    )
    return job_response(row)


@router.get("/generation-tasks/{job_id}/handoff")
def editing_handoff(
    job_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> FileResponse:
    from .video_editing_handoff import export_bundle

    return export_bundle(
        own_job(session, workspace, job_id), request.app.state.settings
    )


@router.get("/generation-tasks/{job_id}/{kind}")
def result_media(
    job_id: UUID,
    kind: Literal["video", "audio"],
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> FileResponse:
    row = own_job(session, workspace, job_id)
    if kind == "video":
        if row.status not in {"completed", "awaiting_review"}:
            raise ApiError(404, "VIDEO_NOT_READY", "视频尚未完成。")
        return FileResponse(
            row.details["result_path"], media_type="video/mp4", filename=row.id + ".mp4"
        )
    if not row.details.get("audio_url"):
        raise ApiError(404, "VIDEO_AUDIO_NOT_FOUND", "音频尚未生成。")
    if row.details.get("audio_local_path"):
        mime = row.details.get("audio_mime", "audio/mpeg")
        suffix = {"audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/mp4": ".m4a"}.get(
            mime, ".mp3"
        )
        return FileResponse(
            row.details["audio_local_path"], media_type=mime, filename=row.id + suffix
        )
    target = request.app.state.settings.video_media_dir / "jobs" / row.id / "audio.mp3"
    url = row.details["audio_url"]
    session.commit()
    if not target.exists():
        providers(request).download(url, target, limit=50 * 1024 * 1024)
    return FileResponse(target, media_type="audio/mpeg")
