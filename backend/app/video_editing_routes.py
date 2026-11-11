"""Owner-created, expiring per-job delegation. Tokens never appear in URLs."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import (
    Principal,
    SessionDependency,
    WorkspaceContext,
    require_workspace_write,
)
from .config import Settings
from .domain import UserStatus
from .errors import ApiError
from .models import UserRecord, WorkspaceMemberRecord, WorkspaceRecord
from .video_editing_handoff import build_manifest
from .video_editing_models import VideoEditingHandoffRecord
from .video_generation import own_job
from .video_generation_models import VideoGenerationRecord
from .video_studio_access import require_video_studio_access
from .video_studio_routes import VideoWorkspace
from .video_studio_schemas import StrictVideoModel

router = APIRouter(tags=["video-editing"])
ROOT = (
    "/api/v1/video-studio/workspaces/{workspace_id}"
    "/generation-tasks/{job_id}/editing-handoffs"
)
SERVICE_ROOT = "/api/v1/video-studio/editing-handoffs"


class HandoffRequest(StrictVideoModel):
    request_id: UUID
    expires_in_seconds: int = Field(default=3600, ge=60, le=86400)


class EditingEvent(StrictVideoModel):
    event_id: UUID
    sequence: int = Field(ge=1, le=100)
    status: Literal["accepted", "aligning", "editing", "result_ready", "failed"]
    service_task_id: str = Field(min_length=1, max_length=120)
    script_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    result_reference: str | None = Field(default=None, max_length=1000)
    error_code: str | None = Field(default=None, max_length=80)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def token_for(
    row: VideoEditingHandoffRecord, settings: Settings, *, legacy_offset: bool = False
) -> str:
    key = settings.video_editing_handoff_secret.get_secret_value()
    if len(key) < 32:
        raise ApiError(503, "VIDEO_EDITING_NOT_CONFIGURED", "剪辑服务交接尚未配置。")
    expires_at = row.expires_at if legacy_offset else utc(row.expires_at)
    message = (
        f"editing-v1:{row.id}:{row.generation_task_id}:{row.workspace_id}:"
        f"{row.owner_user_id}:{expires_at.isoformat()}"
    )
    return "vh1." + hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()


def metadata(row: VideoEditingHandoffRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "generation_task_id": row.generation_task_id,
        "expires_at": utc(row.expires_at).isoformat(),
        "revoked": row.revoked,
        "status": row.status,
        "revision": row.revision,
        "events": row.events,
        "result_reference": row.result_reference,
    }


def owner_record(
    session: Session,
    workspace: WorkspaceContext,
    job_id: str | UUID,
    handoff_id: str | UUID,
) -> VideoEditingHandoffRecord:
    own_job(session, workspace, job_id)
    row = session.get(VideoEditingHandoffRecord, str(handoff_id))
    if (
        not row
        or row.generation_task_id != str(job_id)
        or row.workspace_id != workspace.workspace_id
        or row.owner_user_id != workspace.principal.user_id
    ):
        raise ApiError(404, "VIDEO_EDITING_NOT_FOUND", "未找到剪辑交接。")
    return row


def service_record(
    request: Request,
    session: Session,
    handoff_id: str | UUID,
    authorization: str | None,
) -> VideoEditingHandoffRecord:
    row = session.get(VideoEditingHandoffRecord, str(handoff_id))
    if not row or not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "VIDEO_EDITING_UNAUTHORIZED", "剪辑访问凭据无效。")
    settings = request.app.state.settings
    supplied = authorization[7:]
    matches = hmac.compare_digest(supplied, token_for(row, settings))
    if not matches and row.expires_at.utcoffset():
        # Previously issued v1 tokens may have used the database's offset.
        matches = hmac.compare_digest(
            supplied, token_for(row, settings, legacy_offset=True)
        )
    if row.revoked or utc(row.expires_at) <= datetime.now(UTC) or not matches:
        raise ApiError(401, "VIDEO_EDITING_UNAUTHORIZED", "剪辑访问凭据无效或已过期。")
    owner = session.get(UserRecord, row.owner_user_id)
    workspace = session.get(WorkspaceRecord, row.workspace_id)
    member = session.get(WorkspaceMemberRecord, (row.workspace_id, row.owner_user_id))
    if (
        not owner
        or not workspace
        or workspace.status != "active"
        or not member
        or member.status != "active"
        or member.role not in {"owner", "admin", "editor"}
    ):
        raise ApiError(401, "VIDEO_EDITING_UNAUTHORIZED", "原授权权限已失效。")
    require_video_studio_access(
        Principal(
            user_id=owner.id,
            email=owner.email_normalized,
            email_verified=True,
            status=UserStatus(owner.status),
        )
    )
    return row


@router.post(ROOT)
def create_handoff(
    body: HandoffRequest,
    job_id: UUID,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    response: Response,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    response.headers["Cache-Control"] = "no-store"
    job = own_job(session, workspace, job_id)
    if job.kind != "lipsync" or job.status != "completed":
        raise ApiError(409, "VIDEO_HANDOFF_NOT_READY", "口播完成后才能交接剪辑。")
    fingerprint = hashlib.sha256(
        (str(job_id) + body.model_dump_json()).encode()
    ).hexdigest()
    row = session.scalar(
        select(VideoEditingHandoffRecord).where(
            VideoEditingHandoffRecord.workspace_id == workspace.workspace_id,
            VideoEditingHandoffRecord.owner_user_id == workspace.principal.user_id,
            VideoEditingHandoffRecord.request_id == str(body.request_id),
        )
    )
    if row and row.request_hash != fingerprint:
        raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求标识已用于另一条交接。")
    if not row:
        row = VideoEditingHandoffRecord(
            id=str(uuid4()),
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            generation_task_id=job.id,
            request_id=str(body.request_id),
            request_hash=fingerprint,
            expires_at=datetime.now(UTC) + timedelta(seconds=body.expires_in_seconds),
            status="created",
            revision=0,
            events=[],
            revoked=False,
        )
        token_for(
            row, request.app.state.settings
        )  # Fail before storing unusable grants.
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            row = session.scalar(
                select(VideoEditingHandoffRecord).where(
                    VideoEditingHandoffRecord.workspace_id == workspace.workspace_id,
                    VideoEditingHandoffRecord.owner_user_id
                    == workspace.principal.user_id,
                    VideoEditingHandoffRecord.request_id == str(body.request_id),
                )
            )
            if not row or row.request_hash != fingerprint:
                raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求冲突。") from None
    return {
        **metadata(row),
        "access_token": token_for(row, request.app.state.settings),
        "manifest_url": f"{SERVICE_ROOT}/{row.id}/manifest",
        "events_url": f"{SERVICE_ROOT}/{row.id}/events",
    }


@router.get(ROOT + "/{handoff_id}")
def handoff_status(
    job_id: UUID,
    handoff_id: UUID,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    return metadata(owner_record(session, workspace, job_id, handoff_id))


@router.post(ROOT + "/{handoff_id}/revoke")
def revoke_handoff(
    job_id: UUID,
    handoff_id: UUID,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    row = owner_record(session, workspace, job_id, handoff_id)
    row.revoked = True
    session.commit()
    return metadata(row)


@router.get(SERVICE_ROOT + "/{handoff_id}/manifest")
def service_manifest(
    handoff_id: UUID,
    request: Request,
    session: SessionDependency,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    row = service_record(request, session, handoff_id, authorization)
    job = session.get(VideoGenerationRecord, row.generation_task_id)
    if job is None:
        raise ApiError(404, "VIDEO_TASK_NOT_FOUND", "未找到原口播任务。")
    return {
        **build_manifest(job),
        "handoff": metadata(row),
        "assets": {
            kind: f"{SERVICE_ROOT}/{row.id}/assets/{kind}"
            for kind in ["video", "audio", "script"]
        },
    }


@router.get(SERVICE_ROOT + "/{handoff_id}/assets/{kind}")
def service_asset(
    handoff_id: UUID,
    kind: Literal["video", "audio", "script"],
    request: Request,
    session: SessionDependency,
    authorization: str | None = Header(default=None),
) -> Response:
    row = service_record(request, session, handoff_id, authorization)
    job = session.get(VideoGenerationRecord, row.generation_task_id)
    if job is None:
        raise ApiError(404, "VIDEO_TASK_NOT_FOUND", "未找到原口播任务。")
    manifest = build_manifest(job)
    if kind == "script":
        if not manifest["files"]["script"]:
            raise ApiError(
                404, "VIDEO_SCRIPT_NOT_AVAILABLE", "纯音频任务未提供确认稿。"
            )
        return Response(
            job.details["snapshot"]["draft"]["text"],
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )
    path = Path(
        job.details["result_path"]
        if kind == "video"
        else job.details["audio_local_path"]
    )
    return FileResponse(
        path,
        media_type="video/mp4"
        if kind == "video"
        else job.details.get("audio_mime", "audio/mpeg"),
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(SERVICE_ROOT + "/{handoff_id}/events")
def service_event(
    handoff_id: UUID,
    body: EditingEvent,
    request: Request,
    session: SessionDependency,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    row = service_record(request, session, handoff_id, authorization)
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    old = next(
        (event for event in row.events if event["event_id"] == str(body.event_id)), None
    )
    if old:
        if old["hash"] != digest:
            raise ApiError(
                409, "VIDEO_EDITING_EVENT_REUSED", "回调标识已用于其他内容。"
            )
        return metadata(row)
    if row.events and body.service_task_id != row.events[0]["service_task_id"]:
        raise ApiError(409, "VIDEO_EDITING_TASK_CHANGED", "回调的剪辑任务引用不一致。")
    rank = {"created": 0, "accepted": 1, "aligning": 2, "editing": 3, "result_ready": 4}
    if row.status in {"failed", "result_ready"} or body.sequence != row.revision + 1:
        raise ApiError(
            409, "VIDEO_EDITING_EVENT_ORDER", "回调顺序冲突，请查询原交接状态。"
        )
    if body.status != "failed" and rank[body.status] < rank[row.status]:
        raise ApiError(409, "VIDEO_EDITING_EVENT_ORDER", "剪辑状态不能倒退。")
    if body.status == "result_ready":
        job = session.get(VideoGenerationRecord, row.generation_task_id)
        if job is None:
            raise ApiError(404, "VIDEO_TASK_NOT_FOUND", "未找到原口播任务。")
        expected_hash = build_manifest(job)["script_sha256"]
        if not body.result_reference or body.script_sha256 != expected_hash:
            raise ApiError(
                422, "VIDEO_EDITING_RESULT_INVALID", "请返回成片引用与对应确认稿哈希。"
            )
    event = {
        **body.model_dump(mode="json"),
        "hash": digest,
        "received_at": datetime.now(UTC).isoformat(),
    }
    changed = session.execute(
        update(VideoEditingHandoffRecord)
        .where(
            VideoEditingHandoffRecord.id == row.id,
            VideoEditingHandoffRecord.revision == row.revision,
            VideoEditingHandoffRecord.revoked.is_(False),
        )
        .values(
            status=body.status,
            revision=body.sequence,
            events=row.events + [event],
            result_reference=body.result_reference,
        )
    )
    session.commit()
    if cast(CursorResult[Any], changed).rowcount != 1:
        raise ApiError(
            409, "VIDEO_EDITING_EVENT_ORDER", "回调发生并发冲突，请重放原回调。"
        )
    session.refresh(row)
    return metadata(row)
