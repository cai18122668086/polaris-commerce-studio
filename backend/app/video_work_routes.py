"""Contract C2: work batches and work items shared by talking, editing and finishing.

Every row is scoped to (workspace, owner). Batch creation is idempotent on
``request_id``; item updates use ``expected_version`` optimistic locking, and a
retried update whose fields already match is answered with the current row
instead of a conflict.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .errors import ApiError
from .models import utc_now
from .video_editing_task_models import EditingTaskRecord
from .video_generation_models import VideoAudioRecord, VideoGenerationRecord
from .video_studio_access import require_video_studio_access
from .video_studio_routes import VideoWorkspace
from .video_studio_schemas import StrictVideoModel
from .video_work_models import VideoWorkBatchRecord, VideoWorkItemRecord
from .video_writing_models import VideoScriptLibraryEntry

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-work"],
    dependencies=[Depends(require_video_studio_access)],
)

MAX_BATCH_ITEMS = 20
BatchSource = Literal["talking", "editing_upload"]
DriveMode = Literal["text", "audio", "uploaded_video"]
Stage = Literal["talking", "editing", "finishing", "done"]
Status = Literal["pending", "queued", "running", "succeeded", "failed", "canceled"]
NOT_FOUND = ("VIDEO_WORK_ITEM_NOT_FOUND", "未找到这条作品。")


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class SourceVideoRef(StrictVideoModel):
    """Editing input: a talking result, a library video or an upload."""

    kind: Literal["talking", "library", "upload"]
    id: str = Field(min_length=1, max_length=80)


class WorkItemFields(StrictVideoModel):
    script_document_id: str | None = Field(default=None, max_length=40)
    publish_title: str = Field(default="", max_length=80)
    publish_body: str = Field(default="", max_length=2000)
    script_text: str = Field(default="", max_length=3000)
    persona_id: str | None = Field(default=None, max_length=80)
    avatar_id: str | None = Field(default=None, max_length=80)
    voice_id: str | None = Field(default=None, max_length=80)
    audio_file_id: str | None = Field(default=None, max_length=40)
    source_video_ref: SourceVideoRef | None = None

    _strip_text = field_validator(
        "publish_title",
        "publish_body",
        "script_text",
        "script_document_id",
        "persona_id",
        "avatar_id",
        "voice_id",
        "audio_file_id",
        mode="before",
    )(_strip)


class WorkItemCreate(WorkItemFields):
    drive_mode: DriveMode = "text"

    @model_validator(mode="after")
    def drive_inputs(self) -> WorkItemCreate:
        if self.drive_mode == "text" and not self.script_text:
            raise ValueError("文本驱动需要口播稿。")
        if self.drive_mode == "audio" and not self.audio_file_id:
            raise ValueError("音频驱动需要上传音频。")
        if self.drive_mode == "uploaded_video" and self.source_video_ref is None:
            raise ValueError("直接剪辑需要指定视频。")
        return self


class WorkBatchCreate(StrictVideoModel):
    request_id: UUID
    source: BatchSource = "talking"
    items: list[WorkItemCreate] = Field(min_length=1, max_length=MAX_BATCH_ITEMS)

    @model_validator(mode="after")
    def source_matches_items(self) -> WorkBatchCreate:
        uploaded = {item.drive_mode == "uploaded_video" for item in self.items}
        if self.source == "editing_upload" and uploaded != {True}:
            raise ValueError("直接剪辑批次的每条都需是上传/视频库视频。")
        if self.source == "talking" and True in uploaded:
            raise ValueError("口播批次不能包含直接剪辑的视频。")
        return self


class WorkItemPatch(WorkItemFields):
    """Partial update; only fields that are sent are written.

    Ownership by line (not enforced by the server): W2 writes persona/avatar/
    voice/audio/generation_task_id; W3 writes source_video_ref/editing_task_id;
    W5 writes cover_asset_id and the final publish_title/publish_body. Each line
    moves ``stage``/``status``/``error`` while the item is in its stage.
    """

    expected_version: int = Field(ge=1)
    publish_title: str | None = Field(default=None, max_length=80)  # type: ignore[assignment]
    publish_body: str | None = Field(default=None, max_length=2000)  # type: ignore[assignment]
    script_text: str | None = Field(default=None, max_length=3000)  # type: ignore[assignment]
    generation_task_id: str | None = Field(default=None, max_length=40)
    editing_task_id: str | None = Field(default=None, max_length=40)
    cover_asset_id: str | None = Field(default=None, max_length=80)
    stage: Stage | None = None
    status: Status | None = None
    error: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def not_empty(self) -> WorkItemPatch:
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("没有要更新的字段。")
        for name in ("stage", "status", "publish_title", "publish_body", "script_text"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能为空。")
        return self


class WorkItemResponse(StrictVideoModel):
    id: str
    batch_id: str
    position: int
    version: int
    created_at: datetime
    updated_at: datetime
    script_document_id: str | None
    publish_title: str
    publish_body: str
    script_text: str
    persona_id: str | None
    avatar_id: str | None
    voice_id: str | None
    drive_mode: DriveMode
    audio_file_id: str | None
    generation_task_id: str | None
    source_video_ref: SourceVideoRef | None
    editing_task_id: str | None
    cover_asset_id: str | None
    stage: Stage
    status: Status
    error: str | None
    history: dict[str, list[str]]


class WorkBatchResponse(StrictVideoModel):
    id: str
    source: BatchSource
    created_at: datetime
    item_ids: list[str]
    items: list[WorkItemResponse]
    status_counts: dict[str, int]


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _owner(workspace: WorkspaceContext) -> tuple[str, str]:
    return workspace.workspace_id, workspace.principal.user_id


def item_response(row: VideoWorkItemRecord) -> WorkItemResponse:
    return WorkItemResponse(
        id=row.id,
        batch_id=row.batch_id,
        position=row.position,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        script_document_id=row.script_document_id,
        publish_title=row.publish_title,
        publish_body=row.publish_body,
        script_text=row.script_text,
        persona_id=row.persona_id,
        avatar_id=row.avatar_id,
        voice_id=row.voice_id,
        drive_mode=cast(DriveMode, row.drive_mode),
        audio_file_id=row.audio_file_id,
        generation_task_id=row.generation_task_id,
        source_video_ref=SourceVideoRef.model_validate(row.source_video_ref)
        if row.source_video_ref
        else None,
        editing_task_id=row.editing_task_id,
        cover_asset_id=row.cover_asset_id,
        stage=cast(Stage, row.stage),
        status=cast(Status, row.status),
        error=row.error,
        history=row.history or {},
    )


def batch_items(session: Session, batch_id: str) -> list[VideoWorkItemRecord]:
    return list(
        session.scalars(
            select(VideoWorkItemRecord)
            .where(VideoWorkItemRecord.batch_id == batch_id)
            .order_by(VideoWorkItemRecord.position)
        )
    )


def batch_response(
    batch: VideoWorkBatchRecord, items: list[VideoWorkItemRecord]
) -> WorkBatchResponse:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    return WorkBatchResponse(
        id=batch.id,
        source=cast(BatchSource, batch.source),
        created_at=batch.created_at,
        item_ids=[item.id for item in items],
        items=[item_response(item) for item in items],
        status_counts=counts,
    )


def _owned(session: Session, model: Any, row_id: str, owner: tuple[str, str]) -> bool:
    row = session.get(model, row_id)
    return row is not None and (row.workspace_id, row.owner_user_id) == owner


def _check_refs(
    session: Session, owner: tuple[str, str], fields: dict[str, Any]
) -> None:
    """References must point at the caller's own rows in this workspace."""
    doc_id = fields.get("script_document_id")
    if doc_id:
        entry = session.get(VideoScriptLibraryEntry, doc_id)
        if (
            entry is None
            or entry.deleted_at is not None
            or (entry.workspace_id, entry.owner_user_id) != owner
        ):
            raise ApiError(422, "VIDEO_WORK_REFERENCE_INVALID", "文案不存在或已删除。")
    checks = (
        ("audio_file_id", VideoAudioRecord, "音频"),
        ("generation_task_id", VideoGenerationRecord, "口播任务"),
        ("editing_task_id", EditingTaskRecord, "剪辑任务"),
    )
    for name, model, label in checks:
        value = fields.get(name)
        if value and not _owned(session, model, value, owner):
            raise ApiError(
                422, "VIDEO_WORK_REFERENCE_INVALID", f"{label}不存在或无权使用。"
            )
    ref = fields.get("source_video_ref")
    if (
        ref
        and ref["kind"] == "talking"
        and not _owned(session, VideoGenerationRecord, ref["id"], owner)
    ):
        raise ApiError(
            422, "VIDEO_WORK_REFERENCE_INVALID", "口播视频不存在或无权使用。"
        )


def _existing_batch(
    session: Session, owner: tuple[str, str], request_id: str, fingerprint: str
) -> WorkBatchResponse | None:
    batch = session.scalar(
        select(VideoWorkBatchRecord).where(
            VideoWorkBatchRecord.workspace_id == owner[0],
            VideoWorkBatchRecord.owner_user_id == owner[1],
            VideoWorkBatchRecord.request_id == request_id,
        )
    )
    if batch is None:
        return None
    if batch.request_hash != fingerprint:
        raise ApiError(
            409, "VIDEO_REQUEST_REUSED", "这个提交编号已用于其他内容，请重新提交。"
        )
    return batch_response(batch, batch_items(session, batch.id))


@router.post("/work-batches", response_model=WorkBatchResponse)
def create_batch(
    body: WorkBatchCreate, workspace: VideoWorkspace, session: SessionDependency
) -> WorkBatchResponse:
    require_workspace_write(workspace)
    owner = _owner(workspace)
    request_id = str(body.request_id)
    fingerprint = _digest(body.model_dump(mode="json"))
    previous = _existing_batch(session, owner, request_id, fingerprint)
    if previous:
        return previous
    items = [item.model_dump(mode="json") for item in body.items]
    for fields in items:
        _check_refs(session, owner, fields)
    stage = "editing" if body.source == "editing_upload" else "talking"
    # One timestamp for the batch and its items keeps newest-first lists in order.
    now = utc_now()
    batch = VideoWorkBatchRecord(
        id=str(uuid4()),
        workspace_id=owner[0],
        owner_user_id=owner[1],
        source=body.source,
        request_id=request_id,
        request_hash=fingerprint,
        created_at=now,
        updated_at=now,
    )
    rows = [
        VideoWorkItemRecord(
            id=str(uuid4()),
            batch_id=batch.id,
            workspace_id=owner[0],
            owner_user_id=owner[1],
            position=position,
            version=1,
            stage=stage,
            status="pending",
            history={},
            created_at=now,
            updated_at=now,
            **fields,
        )
        for position, fields in enumerate(items)
    ]
    try:
        session.add(batch)
        session.flush()
        session.add_all(rows)
        session.commit()
    except IntegrityError:
        session.rollback()
        previous = _existing_batch(session, owner, request_id, fingerprint)
        if previous:
            return previous
        raise
    return batch_response(batch, rows)


@router.get("/work-batches", response_model=list[WorkBatchResponse])
def list_batches(
    workspace: VideoWorkspace,
    session: SessionDependency,
    source: BatchSource | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[WorkBatchResponse]:
    owner = _owner(workspace)
    query = select(VideoWorkBatchRecord).where(
        VideoWorkBatchRecord.workspace_id == owner[0],
        VideoWorkBatchRecord.owner_user_id == owner[1],
    )
    if source:
        query = query.where(VideoWorkBatchRecord.source == source)
    batches = session.scalars(
        query.order_by(VideoWorkBatchRecord.created_at.desc(), VideoWorkBatchRecord.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return [batch_response(batch, batch_items(session, batch.id)) for batch in batches]


@router.get("/work-batches/{batch_id}", response_model=WorkBatchResponse)
def get_batch(
    batch_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> WorkBatchResponse:
    batch = session.get(VideoWorkBatchRecord, batch_id)
    if batch is None or (batch.workspace_id, batch.owner_user_id) != _owner(workspace):
        raise ApiError(404, "VIDEO_WORK_BATCH_NOT_FOUND", "未找到这个批次。")
    return batch_response(batch, batch_items(session, batch.id))


@router.get("/work-items", response_model=list[WorkItemResponse])
def list_items(
    workspace: VideoWorkspace,
    session: SessionDependency,
    batch_id: str | None = None,
    ids: str | None = Query(None, max_length=2000, description="逗号分隔的条目 id"),
    stage: Annotated[list[Stage] | None, Query()] = None,
    status: Annotated[list[Status] | None, Query()] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[WorkItemResponse]:
    owner = _owner(workspace)
    query = select(VideoWorkItemRecord).where(
        VideoWorkItemRecord.workspace_id == owner[0],
        VideoWorkItemRecord.owner_user_id == owner[1],
    )
    if batch_id:
        query = query.where(VideoWorkItemRecord.batch_id == batch_id)
    if ids:
        wanted = [value.strip() for value in ids.split(",") if value.strip()][:200]
        query = query.where(VideoWorkItemRecord.id.in_(wanted))
    if stage:
        query = query.where(VideoWorkItemRecord.stage.in_(stage))
    if status:
        query = query.where(VideoWorkItemRecord.status.in_(status))
    order = (
        (VideoWorkItemRecord.position,)
        if batch_id
        else (
            VideoWorkItemRecord.created_at.desc(),
            VideoWorkItemRecord.batch_id,
            VideoWorkItemRecord.position,
        )
    )
    rows = session.scalars(query.order_by(*order).limit(limit).offset(offset)).all()
    return [item_response(row) for row in rows]


def _owned_item(
    session: Session, workspace: WorkspaceContext, item_id: str
) -> VideoWorkItemRecord:
    row = session.get(VideoWorkItemRecord, item_id)
    if row is None or (row.workspace_id, row.owner_user_id) != _owner(workspace):
        raise ApiError(404, *NOT_FOUND)
    return row


@router.get("/work-items/{item_id}", response_model=WorkItemResponse)
def get_item(
    item_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> WorkItemResponse:
    return item_response(_owned_item(session, workspace, item_id))


def _stored(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


@router.patch("/work-items/{item_id}", response_model=WorkItemResponse)
def patch_item(
    item_id: str,
    body: WorkItemPatch,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> WorkItemResponse:
    require_workspace_write(workspace)
    row = _owned_item(session, workspace, item_id)
    changes = {
        name: _stored(getattr(body, name))
        for name in body.model_fields_set - {"expected_version"}
    }
    if row.version != body.expected_version:
        # A retried update that already landed is answered, not refused.
        if all(getattr(row, name) == value for name, value in changes.items()):
            return item_response(row)
        raise ApiError(
            409, "VIDEO_WORK_ITEM_CONFLICT", "这条作品已在别处更新，请刷新后再改。"
        )
    _check_refs(session, _owner(workspace), changes)
    history = {key: list(value) for key, value in (row.history or {}).items()}
    for name, key in (
        ("generation_task_id", "generation"),
        ("editing_task_id", "editing"),
    ):
        old = getattr(row, name)
        if name in changes and old and old != changes[name]:
            history.setdefault(key, []).append(old)
    if history != (row.history or {}):
        changes["history"] = history
    if "status" in changes and changes["status"] != "failed" and "error" not in changes:
        changes["error"] = None
    result = session.execute(
        update(VideoWorkItemRecord)
        .where(
            VideoWorkItemRecord.id == row.id,
            VideoWorkItemRecord.version == body.expected_version,
        )
        .values(**changes, version=body.expected_version + 1, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult, result).rowcount != 1:
        session.rollback()
        raise ApiError(
            409, "VIDEO_WORK_ITEM_CONFLICT", "这条作品已在别处更新，请刷新后再改。"
        )
    session.commit()
    session.refresh(row)
    return item_response(row)
