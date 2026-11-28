"""固定形象 persona 接口（契约 C3）：形象 + 声音搭配好，口播时选一个就带出两者。

- 按「工作区 + 用户」隔离；同一用户内名称唯一（409）；``request_id`` 幂等。
- 形象 / 声音只存 id 与名称快照。依赖对象被删除、下线或暂不可用时，列表照常返回，
  并给出 ``available=false`` 与中文原因，不报错。
- 列表直接带上形象封面、声音名称与试听地址，口播页选择器不需要二次请求。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Request, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .errors import ApiError
from .video_avatar_access import avatar_scope
from .video_generation import providers
from .video_generation_models import VideoAvatarRecord, VideoGenerationRecord
from .video_persona_models import VideoPersonaRecord
from .video_studio_routes import VideoWorkspace
from .video_studio_schemas import StrictVideoModel
from .video_voice_catalog import EMOTIONS, LANGUAGES, official_voices
from .video_voice_cloning import catalog as cloned_voice_catalog
from .video_voice_names import quanyu_display

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}", tags=["video-personas"]
)
PERSONA_LIMIT = 100


class PersonaCreate(StrictVideoModel):
    request_id: UUID
    name: str = Field(min_length=1, max_length=30)
    avatar_id: str = Field(min_length=1, max_length=80)
    voice_id: str = Field(min_length=1, max_length=80)
    emotion: str | None = Field(default=None, max_length=12)
    language: str | None = Field(default=None, max_length=40)


class PersonaUpdate(StrictVideoModel):
    name: str | None = Field(default=None, min_length=1, max_length=30)
    avatar_id: str | None = Field(default=None, min_length=1, max_length=80)
    voice_id: str | None = Field(default=None, min_length=1, max_length=80)
    emotion: str | None = Field(default=None, max_length=12)
    language: str | None = Field(default=None, max_length=40)


class PersonaResponse(StrictVideoModel):
    id: str
    name: str
    avatar_id: str
    voice_id: str
    avatar_name: str
    voice_name: str
    cover_url: str | None
    avatar_preview_url: str | None
    voice_preview_url: str | None
    emotion: str | None
    language: str | None
    available: bool
    unavailable_reason: str | None
    created_at: datetime
    updated_at: datetime


# ---------- 依赖对象解析 ----------


def _avatar_root(workspace: WorkspaceContext, avatar_id: str) -> str:
    return (
        f"/api/v1/video-studio/workspaces/{workspace.workspace_id}/avatars/{avatar_id}"
    )


def avatar_views(
    session: Session, workspace: WorkspaceContext, ids: set[str]
) -> dict[str, dict[str, Any]]:
    """与 ``GET /avatars`` 同一套可见性与就绪判断，只查需要的几个 id。"""
    if not ids:
        return {}
    rows = session.scalars(
        select(VideoAvatarRecord).where(
            VideoAvatarRecord.id.in_(ids), avatar_scope(workspace)
        )
    ).all()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        owned = (
            session.scalar(
                select(VideoGenerationRecord.id)
                .where(
                    VideoGenerationRecord.avatar_id == row.id,
                    VideoGenerationRecord.kind == "h3_template",
                    VideoGenerationRecord.status == "completed",
                    VideoGenerationRecord.workspace_id == workspace.workspace_id,
                    VideoGenerationRecord.owner_user_id == workspace.principal.user_id,
                )
                .limit(1)
            )
            if row.source == "self_owned"
            else None
        )
        root = _avatar_root(workspace, row.id)
        result[row.id] = {
            "name": row.name,
            "active": bool(row.active),
            "ready": bool(row.provider_model_id or owned),
            "cover_url": root + "/cover",
            "preview_url": root + "/preview" if row.video_url or owned else None,
        }
    return result


def voice_views(
    request: Request,
    session: Session,
    workspace: WorkspaceContext,
    ids: set[str],
) -> dict[str, dict[str, Any]]:
    """与 ``GET /voices`` 同源。上游公共音色列表只有用到时才查，失败不影响列表。"""
    if not ids:
        return {}
    settings = request.app.state.settings
    root = f"/api/v1/video-studio/workspaces/{workspace.workspace_id}"
    voices: list[dict[str, Any]] = official_voices(
        settings, root, ids
    ) + cloned_voice_catalog(settings, session, workspace)
    if any(voice_id.startswith("qy-voice-") for voice_id in ids):
        try:
            voices += [
                {
                    "id": "qy-voice-" + str(v["id"]),
                    "name": quanyu_display(
                        str(v["id"]), v.get("name") or v.get("voice_name")
                    )["name"],
                    "available": True,
                    "preview_url": None,
                }
                for v in providers(request).voices()
            ]
        except Exception:  # noqa: BLE001 — 上游不可达时按快照显示，不阻断列表
            logger.warning("persona voice catalogue unavailable", exc_info=True)
            for voice_id in ids:
                if voice_id.startswith("qy-voice-"):
                    voices.append(
                        {
                            "id": voice_id,
                            "name": None,
                            "available": True,
                            "preview_url": None,
                        }
                    )
    return {v["id"]: v for v in voices if v["id"] in ids}


def availability(
    avatar: dict[str, Any] | None, voice: dict[str, Any] | None
) -> tuple[bool, str | None]:
    if avatar is None or not avatar["active"]:
        return False, "形象已删除或不可用，请更换形象"
    if voice is None:
        return False, "声音已删除或不可用，请更换声音"
    if not avatar["ready"]:
        return False, "形象还在定制中，完成后即可使用"
    if not voice.get("available"):
        return False, "声音暂不可用，请稍后再试或更换声音"
    return True, None


def persona_response(
    row: VideoPersonaRecord,
    avatar: dict[str, Any] | None,
    voice: dict[str, Any] | None,
) -> PersonaResponse:
    available, reason = availability(avatar, voice)
    settings = row.voice_settings or {}
    live = avatar if avatar and avatar["active"] else None
    return PersonaResponse(
        id=row.id,
        name=row.name,
        avatar_id=row.avatar_id,
        voice_id=row.voice_id,
        avatar_name=(live or {}).get("name") or row.avatar_name,
        voice_name=(voice or {}).get("name") or row.voice_name,
        cover_url=live["cover_url"] if live else None,
        avatar_preview_url=live["preview_url"] if live else None,
        voice_preview_url=voice.get("preview_url") if voice else None,
        emotion=settings.get("emotion"),
        language=settings.get("language"),
        available=available,
        unavailable_reason=reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def render(
    request: Request,
    session: Session,
    workspace: WorkspaceContext,
    rows: list[VideoPersonaRecord],
) -> list[PersonaResponse]:
    avatars = avatar_views(session, workspace, {row.avatar_id for row in rows})
    voices = voice_views(request, session, workspace, {row.voice_id for row in rows})
    return [
        persona_response(row, avatars.get(row.avatar_id), voices.get(row.voice_id))
        for row in rows
    ]


# ---------- 校验 ----------


def scoped(
    workspace: WorkspaceContext,
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (
        VideoPersonaRecord.workspace_id == workspace.workspace_id,
        VideoPersonaRecord.owner_user_id == workspace.principal.user_id,
    )


def owned_persona(
    session: Session, workspace: WorkspaceContext, persona_id: str
) -> VideoPersonaRecord:
    row = session.scalar(
        select(VideoPersonaRecord).where(
            VideoPersonaRecord.id == persona_id, *scoped(workspace)
        )
    )
    if row is None:
        raise ApiError(404, "VIDEO_PERSONA_NOT_FOUND", "未找到这个固定形象。")
    return row


def clean_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise ApiError(422, "VIDEO_PERSONA_NAME_REQUIRED", "请给固定形象起个名字。")
    return name


def check_settings(emotion: str | None, language: str | None) -> dict[str, str]:
    if emotion is not None and emotion not in EMOTIONS:
        raise ApiError(422, "VIDEO_VOICE_SETTING_INVALID", "请选择此声音支持的情绪。")
    if language is not None and language not in LANGUAGES:
        raise ApiError(422, "VIDEO_VOICE_SETTING_INVALID", "请选择此声音支持的语言。")
    return {
        key: value
        for key, value in {"emotion": emotion, "language": language}.items()
        if value is not None
    }


def resolve_avatar(
    session: Session, workspace: WorkspaceContext, avatar_id: str
) -> dict[str, Any]:
    avatar = avatar_views(session, workspace, {avatar_id}).get(avatar_id)
    # 定制中的形象允许先绑定，完成后自动可用；已删除 / 他人的形象一律 404。
    if avatar is None or not avatar["active"]:
        raise ApiError(404, "VIDEO_AVATAR_NOT_FOUND", "未找到这个形象，请重新选择。")
    return avatar


def resolve_voice(
    request: Request, session: Session, workspace: WorkspaceContext, voice_id: str
) -> dict[str, Any]:
    voice = voice_views(request, session, workspace, {voice_id}).get(voice_id)
    if voice is None:
        raise ApiError(404, "VIDEO_VOICE_INVALID", "未找到这个声音，请重新选择。")
    return voice


def name_taken() -> ApiError:
    return ApiError(409, "VIDEO_PERSONA_NAME_TAKEN", "已有同名的固定形象，换个名字吧。")


def name_exists(
    session: Session,
    workspace: WorkspaceContext,
    name: str,
    exclude: str | None = None,
) -> bool:
    query = select(VideoPersonaRecord.id).where(
        VideoPersonaRecord.name == name, *scoped(workspace)
    )
    if exclude:
        query = query.where(VideoPersonaRecord.id != exclude)
    return session.scalar(query.limit(1)) is not None


# ---------- 路由 ----------


@router.get("/personas", response_model=list[PersonaResponse])
def list_personas(
    request: Request, workspace: VideoWorkspace, session: SessionDependency
) -> list[PersonaResponse]:
    rows = list(
        session.scalars(
            select(VideoPersonaRecord)
            .where(*scoped(workspace))
            .order_by(VideoPersonaRecord.created_at.desc(), VideoPersonaRecord.id)
            .limit(PERSONA_LIMIT)
        ).all()
    )
    return render(request, session, workspace, rows)


@router.get("/personas/{persona_id}", response_model=PersonaResponse)
def get_persona(
    persona_id: str,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> PersonaResponse:
    return render(
        request, session, workspace, [owned_persona(session, workspace, persona_id)]
    )[0]


@router.post("/personas", response_model=PersonaResponse)
def create_persona(
    body: PersonaCreate,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> PersonaResponse:
    require_workspace_write(workspace)
    name = clean_name(body.name)
    settings = check_settings(body.emotion, body.language)

    def existing() -> VideoPersonaRecord | None:
        return session.scalar(
            select(VideoPersonaRecord).where(
                VideoPersonaRecord.request_id == str(body.request_id),
                *scoped(workspace),
            )
        )

    def reconcile(row: VideoPersonaRecord) -> PersonaResponse:
        if (row.name, row.avatar_id, row.voice_id, row.voice_settings or {}) != (
            name,
            body.avatar_id,
            body.voice_id,
            settings,
        ):
            raise ApiError(
                409, "VIDEO_REQUEST_REUSED", "这次提交和之前的内容不同，请刷新后重试。"
            )
        return render(request, session, workspace, [row])[0]

    old = existing()
    if old:
        return reconcile(old)
    if name_exists(session, workspace, name):
        raise name_taken()
    count = session.scalar(
        select(func.count(VideoPersonaRecord.id)).where(*scoped(workspace))
    )
    if (count or 0) >= PERSONA_LIMIT:
        raise ApiError(
            422,
            "VIDEO_PERSONA_LIMIT",
            f"最多保存 {PERSONA_LIMIT} 个固定形象，请先删除不用的。",
        )
    avatar = resolve_avatar(session, workspace, body.avatar_id)
    voice = resolve_voice(request, session, workspace, body.voice_id)
    row = VideoPersonaRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        request_id=str(body.request_id),
        name=name,
        avatar_id=body.avatar_id,
        voice_id=body.voice_id,
        avatar_name=avatar["name"],
        voice_name=voice.get("name") or "声音",
        voice_settings=settings,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        old = existing()
        if old:
            return reconcile(old)
        raise name_taken() from None
    session.refresh(row)
    return persona_response(row, avatar, voice)


@router.patch("/personas/{persona_id}", response_model=PersonaResponse)
def update_persona(
    persona_id: str,
    body: PersonaUpdate,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> PersonaResponse:
    require_workspace_write(workspace)
    row = owned_persona(session, workspace, persona_id)
    if body.name is not None:
        name = clean_name(body.name)
        if name != row.name and name_exists(session, workspace, name, exclude=row.id):
            raise name_taken()
        row.name = name
    if body.avatar_id is not None and body.avatar_id != row.avatar_id:
        avatar = resolve_avatar(session, workspace, body.avatar_id)
        row.avatar_id, row.avatar_name = body.avatar_id, avatar["name"]
    if body.voice_id is not None and body.voice_id != row.voice_id:
        voice = resolve_voice(request, session, workspace, body.voice_id)
        row.voice_id, row.voice_name = body.voice_id, voice.get("name") or "声音"
        row.voice_settings = {}
    if body.emotion is not None or body.language is not None:
        merged = {**(row.voice_settings or {})}
        merged.update(check_settings(body.emotion, body.language))
        row.voice_settings = merged
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise name_taken() from None
    session.refresh(row)
    return render(request, session, workspace, [row])[0]


@router.delete("/personas/{persona_id}", status_code=204)
def delete_persona(
    persona_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> Response:
    require_workspace_write(workspace)
    row = owned_persona(session, workspace, persona_id)
    session.delete(row)
    session.commit()
    return Response(status_code=204)
