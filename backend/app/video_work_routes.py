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
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .errors import ApiError
from .models import utc_now
from .video_cover_models import VideoCoverCandidateRecord
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
# 我的作品的分组（B1/B2）：每条作品恰好属于一组，列表过滤与计数共用同一口径。
#   active    生成中/剪辑中（status queued|running）
#   failed    失败或已取消（status failed|canceled）
#   done      已成片（stage done）
#   finishing 已剪好、待成片（stage finishing）
#   other     其余：口播已完成待剪辑，或还没确认生成（stage talking|editing）
Group = Literal["active", "failed", "done", "finishing", "other"]
GROUPS: tuple[Group, ...] = ("active", "failed", "done", "finishing", "other")
ACTIVE_STATUSES = ("queued", "running")
FAILED_STATUSES = ("failed", "canceled")


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


class WorkItemUpdate(WorkItemFields):
    """Server-side partial update (stage code only, never a request body).

    Talking, editing and finishing write their task ids, ``stage``, ``status``
    and ``error`` through this; the public ``PATCH`` accepts only
    ``WorkItemPatch`` (content fields), see B9.
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
    # C10：商家自己的「已发布」标记。
    # true 记下当前时间（已标记的保持原时间），false 清除。
    published: bool | None = None

    @model_validator(mode="after")
    def not_empty(self) -> WorkItemUpdate:
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("没有要更新的字段。")
        for name in (
            "stage",
            "status",
            "publish_title",
            "publish_body",
            "script_text",
            "published",
        ):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能为空。")
        return self


class WorkItemPatch(StrictVideoModel):
    """Public partial update: content only (B9).

    Stage, status, error and task ids are written by the server's stage code
    (talking, editing, ``adopt-editing``, ``finish``), never by a request body,
    so a stale tab or a replayed request cannot move an item between stages.
    """

    expected_version: int = Field(ge=1)
    script_document_id: str | None = Field(default=None, max_length=40)
    publish_title: str | None = Field(default=None, max_length=80)
    publish_body: str | None = Field(default=None, max_length=2000)
    script_text: str | None = Field(default=None, max_length=3000)
    persona_id: str | None = Field(default=None, max_length=80)
    avatar_id: str | None = Field(default=None, max_length=80)
    voice_id: str | None = Field(default=None, max_length=80)
    audio_file_id: str | None = Field(default=None, max_length=40)
    # C10：商家自己的「已发布」标记。
    # true 记下当前时间（已标记的保持原时间），false 清除。
    published: bool | None = None

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

    @model_validator(mode="after")
    def not_empty(self) -> WorkItemPatch:
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("没有要更新的字段。")
        for name in ("publish_title", "publish_body", "script_text", "published"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能为空。")
        return self


class AdoptEditingRequest(StrictVideoModel):
    editing_task_id: str = Field(min_length=1, max_length=40)


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
    deleted_at: datetime | None = None
    published_at: datetime | None = None


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
        deleted_at=row.deleted_at,
        published_at=row.published_at,
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


def require_sources_not_owned(
    session: Session,
    owner: tuple[str, str],
    batch_id: str | None,
    items: list[dict[str, Any]],
) -> None:
    """A talking result is edited as its own work item, never a copy (B9).

    Its title, body and script live on the talking batch's item; a second item
    in a direct-editing batch would lose them in finishing and works. Checked
    when the batch is created and again when editing is submitted.
    """
    generations = [
        str((fields.get("source_video_ref") or {}).get("id"))
        for fields in items
        if (fields.get("source_video_ref") or {}).get("kind") in {"library", "talking"}
    ]
    if not generations:
        return
    found = session.scalar(
        select(VideoWorkItemRecord).where(
            VideoWorkItemRecord.workspace_id == owner[0],
            VideoWorkItemRecord.owner_user_id == owner[1],
            *((VideoWorkItemRecord.batch_id != batch_id,) if batch_id else ()),
            VideoWorkItemRecord.generation_task_id.in_(generations),
        )
    )
    if found is not None:
        raise ApiError(
            409,
            "VIDEO_WORK_SOURCE_HAS_ITEM",
            "这条口播属于一个口播批次，请从那一批进入剪辑，标题和正文才不会丢。",
            {"batch_id": found.batch_id, "item_id": found.id},
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
    if body.source == "editing_upload":
        require_sources_not_owned(session, owner, None, items)
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


def group_filter(groups: list[Group]) -> Any:
    """SQL predicate for the given groups (same rule as ``group_of``)."""
    item = VideoWorkItemRecord
    settled = item.status.not_in(ACTIVE_STATUSES + FAILED_STATUSES)
    clauses = {
        "active": item.status.in_(ACTIVE_STATUSES),
        "failed": item.status.in_(FAILED_STATUSES),
        "done": and_(item.stage == "done", settled),
        "finishing": and_(item.stage == "finishing", settled),
        "other": and_(item.stage.in_(("talking", "editing")), settled),
    }
    return or_(*(clauses[group] for group in groups))


def group_of(stage: str, status: str) -> Group:
    if status in ACTIVE_STATUSES:
        return "active"
    if status in FAILED_STATUSES:
        return "failed"
    if stage == "done":
        return "done"
    if stage == "finishing":
        return "finishing"
    return "other"


def item_list_query(
    session: Session,
    owner: tuple[str, str],
    *,
    batch_id: str | None = None,
    ids: list[str] | None = None,
    stage: list[str] | None = None,
    status: list[str] | None = None,
    group: list[Group] | None = None,
    after: str | None = None,
) -> Select[tuple[VideoWorkItemRecord]]:
    """Newest first; inside one batch by position. ``after`` = the last item id
    of the previous page (keyset paging: rows sharing a batch timestamp are
    ordered by ``batch_id, position``, so no row is skipped or repeated)."""
    item = VideoWorkItemRecord
    query = select(item).where(
        item.workspace_id == owner[0],
        item.owner_user_id == owner[1],
        item.deleted_at.is_(None),
    )
    if batch_id:
        query = query.where(item.batch_id == batch_id)
    if ids is not None:
        query = query.where(item.id.in_(ids))
    if stage:
        query = query.where(item.stage.in_(stage))
    if status:
        query = query.where(item.status.in_(status))
    if group:
        query = query.where(group_filter(group))
    if after:
        anchor = session.get(item, after)
        if anchor is None or (anchor.workspace_id, anchor.owner_user_id) != owner:
            raise ApiError(422, "VIDEO_WORK_CURSOR_INVALID", "翻页位置无效，请刷新。")
        if batch_id:
            query = query.where(item.position > anchor.position)
        else:
            query = query.where(
                or_(
                    item.created_at < anchor.created_at,
                    and_(
                        item.created_at == anchor.created_at,
                        item.batch_id > anchor.batch_id,
                    ),
                    and_(
                        item.created_at == anchor.created_at,
                        item.batch_id == anchor.batch_id,
                        item.position > anchor.position,
                    ),
                )
            )
    order = (
        (item.position,)
        if batch_id
        else (item.created_at.desc(), item.batch_id, item.position)
    )
    return query.order_by(*order)


@router.get("/work-items", response_model=list[WorkItemResponse])
def list_items(
    workspace: VideoWorkspace,
    session: SessionDependency,
    batch_id: str | None = None,
    ids: str | None = Query(None, max_length=2000, description="逗号分隔的条目 id"),
    stage: Annotated[list[Stage] | None, Query()] = None,
    status: Annotated[list[Status] | None, Query()] = None,
    group: Annotated[
        list[Group] | None,
        Query(description="只看这些分组；只看已完成 = group=done"),
    ] = None,
    after: str | None = Query(
        None, max_length=40, description="上一页最后一条的 id（游标翻页）"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[WorkItemResponse]:
    """Deleted items are never listed. Page with ``after``: pass the id of the
    last item received; a page shorter than ``limit`` is the last one."""
    wanted = (
        [value.strip() for value in ids.split(",") if value.strip()][:200]
        if ids
        else None
    )
    query = item_list_query(
        session,
        _owner(workspace),
        batch_id=batch_id,
        ids=wanted,
        stage=list(stage) if stage else None,
        status=list(status) if status else None,
        group=list(group) if group else None,
        after=after,
    )
    rows = session.scalars(query.limit(limit).offset(offset)).all()
    return [item_response(row) for row in rows]


class WorkItemSummary(StrictVideoModel):
    total: int
    active: int
    failed: int
    done: int
    finishing: int
    other: int


def item_summary(session: Session, owner: tuple[str, str]) -> WorkItemSummary:
    item = VideoWorkItemRecord
    counts = dict.fromkeys(GROUPS, 0)
    rows = session.execute(
        select(item.stage, item.status, func.count(item.id))
        .where(
            item.workspace_id == owner[0],
            item.owner_user_id == owner[1],
            item.deleted_at.is_(None),
        )
        .group_by(item.stage, item.status)
    ).all()
    for stage_value, status_value, count in rows:
        counts[group_of(stage_value, status_value)] += int(count)
    return WorkItemSummary(total=sum(counts.values()), **counts)


@router.get("/work-items/summary", response_model=WorkItemSummary)
def work_item_summary(
    workspace: VideoWorkspace, session: SessionDependency
) -> WorkItemSummary:
    """我的作品的计数（不含已删除），与 ``group`` 过滤同一口径。"""
    return item_summary(session, _owner(workspace))


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
    """Edit an item's content (title, body, script, presenter, voice, audio)."""
    fields = body.model_dump(exclude_unset=True)
    return update_item(item_id, WorkItemUpdate(**fields), workspace, session)


def update_item(
    item_id: str,
    body: WorkItemUpdate,
    workspace: WorkspaceContext,
    session: Session,
) -> WorkItemResponse:
    """Versioned update shared by PATCH and the stage endpoints."""
    require_workspace_write(workspace)
    row = _owned_item(session, workspace, item_id)
    if row.deleted_at is not None:
        raise ApiError(404, *NOT_FOUND)
    changes = {
        name: _stored(getattr(body, name))
        for name in body.model_fields_set - {"expected_version", "published"}
    }
    if "published" in body.model_fields_set:
        changes["published_at"] = (
            (row.published_at or utc_now()) if body.published else None
        )
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


@router.post("/work-items/{item_id}/adopt-editing", response_model=WorkItemResponse)
def adopt_editing(
    item_id: str,
    body: AdoptEditingRequest,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> WorkItemResponse:
    """Use a finished editing task (e.g. 精修这一条) as this item's video.

    Idempotent. The replaced task id goes to ``history["editing"]`` and
    ``history["video_updated"]`` records when the video changed (the finishing
    page offers a new cover then). An item still in editing moves on to
    finishing (待成片).
    """
    require_workspace_write(workspace)
    owner = _owner(workspace)
    for _ in range(3):
        row = _owned_item(session, workspace, item_id)
        if row.deleted_at is not None:
            raise ApiError(404, *NOT_FOUND)
        if row.editing_task_id == body.editing_task_id:
            return item_response(row)
        task = session.get(EditingTaskRecord, body.editing_task_id)
        if task is None or (task.workspace_id, task.owner_user_id) != owner:
            raise ApiError(
                422, "VIDEO_WORK_REFERENCE_INVALID", "剪辑任务不存在或无权使用。"
            )
        if task.status != "completed":
            raise ApiError(409, "VIDEO_WORK_EDITING_NOT_DONE", "这一版还没有剪好。")
        changes: dict[str, Any] = {"editing_task_id": task.id}
        history = {key: list(value) for key, value in (row.history or {}).items()}
        if row.editing_task_id:
            history.setdefault("editing", []).append(row.editing_task_id)
            history["video_updated"] = [utc_now().isoformat()]
        changes["history"] = history
        if row.stage == "editing":
            changes.update(stage="finishing", status="pending", error=None)
        result = session.execute(
            update(VideoWorkItemRecord)
            .where(
                VideoWorkItemRecord.id == row.id,
                VideoWorkItemRecord.version == row.version,
            )
            .values(**changes, version=row.version + 1, updated_at=utc_now())
            .execution_options(synchronize_session=False)
        )
        if cast(CursorResult, result).rowcount == 1:
            session.commit()
            session.refresh(row)
            return item_response(row)
        session.rollback()  # Someone else updated it: read again and retry.
        session.expire_all()
    raise ApiError(
        409, "VIDEO_WORK_ITEM_CONFLICT", "这条作品已在别处更新，请刷新后再试。"
    )


def item_busy(session: Session, row: VideoWorkItemRecord) -> bool:
    """Generating, editing or making a cover right now."""
    if row.status in ACTIVE_STATUSES:
        return True
    cover = session.scalar(
        select(VideoCoverCandidateRecord.id)
        .where(
            VideoCoverCandidateRecord.work_item_id == row.id,
            VideoCoverCandidateRecord.status.in_(("queued", "running")),
        )
        .limit(1)
    )
    return cover is not None


@router.delete("/work-items/{item_id}", response_model=WorkItemResponse)
def delete_item(
    item_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> WorkItemResponse:
    """Soft delete (B1): the item leaves every list; its batch, tasks and files
    stay. Repeating the call answers the deleted row. Items still generating,
    editing or making a cover are refused."""
    require_workspace_write(workspace)
    row = _owned_item(session, workspace, item_id)
    if row.deleted_at is not None:
        return item_response(row)
    if item_busy(session, row):
        raise ApiError(
            409, "VIDEO_WORK_ITEM_BUSY", "这条还在生成或剪辑中，完成或失败后才能删除。"
        )
    now = utc_now()
    result = session.execute(
        update(VideoWorkItemRecord)
        .where(
            VideoWorkItemRecord.id == row.id,
            VideoWorkItemRecord.version == row.version,
            VideoWorkItemRecord.deleted_at.is_(None),
            VideoWorkItemRecord.status.not_in(ACTIVE_STATUSES),
        )
        .values(deleted_at=now, version=row.version + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if cast(CursorResult, result).rowcount != 1:
        session.rollback()
        raise ApiError(
            409, "VIDEO_WORK_ITEM_CONFLICT", "这条作品刚刚有变化，请刷新后再删。"
        )
    session.commit()
    session.refresh(row)
    return item_response(row)
