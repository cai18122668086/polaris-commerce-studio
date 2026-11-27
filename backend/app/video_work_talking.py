"""Talking stage for work batches: every item becomes its own paid lipsync task.

One batch submit creates (at most) one task per item, each with a request id
derived from the item and its attempt number, so repeated clicks, page reloads
and lost responses can never create or charge a second task. At most
``TALKING_PARALLEL`` tasks per user run at once; the rest wait in the batch and
start as earlier ones finish. A failed item can be retried on its own.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from threading import Thread
from typing import Any, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from .auth import (
    Principal,
    SessionDependency,
    WorkspaceContext,
    require_workspace_write,
)
from .config import Settings
from .domain import MembershipRole, MembershipStatus
from .errors import ApiError
from .models import WorkspaceMemberRecord, utc_now
from .video_generation import (
    ACTIVE_VIDEO_STATUSES,
    GenerationRequest,
    create_generation,
    process_generation,
    providers,
)
from .video_generation_models import VideoGenerationRecord
from .video_providers import VideoProviders
from .video_studio_access import require_video_studio_access
from .video_studio_models import VideoProjectRecord
from .video_studio_routes import VideoWorkspace, append_version
from .video_studio_schemas import StrictVideoModel, VideoDraft, VideoProjectContent
from .video_work_models import VideoWorkBatchRecord, VideoWorkItemRecord
from .video_work_routes import WorkBatchResponse, batch_items, batch_response

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-work"],
    dependencies=[Depends(require_video_studio_access)],
)

TALKING_PARALLEL = 4
NAMESPACE = UUID("6f1d3c52-6b0e-4d5e-9a8f-2b8d0f3c7a11")
GENERATION_TO_ITEM = {
    "queued": "queued",
    "running": "running",
    "awaiting_resume": "running",
    "unknown": "running",
    "completed": "succeeded",
    "failed": "failed",
    "rejected": "failed",
    "review_rejected": "failed",
}
ERROR_COPY = {
    "VIDEO_TEMPLATE_NOT_READY": "这个数字人的动作还没准备好，换一个形象再试。",
    "VIDEO_VOICE_INVALID": "所选音色暂不可用，换一个音色再试。",
    "VIDEO_TTS_NOT_CONFIGURED": "所选音色暂不可用，换一个音色再试。",
    "VIDEO_AUDIO_NOT_FOUND": "音频读取失败，请重新上传。",
}
DEFAULT_ERROR = "这条没有生成成功，未扣积分，可以单独重试。"
ProviderFactory = Callable[[], VideoProviders]


def attempt(item: VideoWorkItemRecord) -> int:
    return len((item.history or {}).get("generation", []))


def talking_request_id(item: VideoWorkItemRecord) -> UUID:
    return uuid5(NAMESPACE, f"talking:{item.id}:{attempt(item)}")


def talking_project_id(item: VideoWorkItemRecord) -> UUID:
    return uuid5(NAMESPACE, f"project:{item.id}:{attempt(item)}")


def item_content(item: VideoWorkItemRecord) -> dict[str, Any]:
    name = (item.publish_title or item.script_text[:18] or "口播").strip()[:80]
    draft = VideoDraft(
        name=name or "口播",
        text=item.script_text,
        avatarId=item.avatar_id or "",
        voiceId=item.voice_id or "",
        drive="audio" if item.drive_mode == "audio" else "text",
        audioAssetId=UUID(item.audio_file_id) if item.audio_file_id else None,
    )
    return VideoProjectContent(draft=draft).model_dump(mode="json")


def ensure_project(
    session: Session, workspace: WorkspaceContext, item: VideoWorkItemRecord
) -> VideoProjectRecord:
    """The lipsync task reads its script from a project; one per item attempt."""
    project_id = str(talking_project_id(item))
    row = session.get(VideoProjectRecord, project_id)
    if row is not None:
        if (row.workspace_id, row.owner_user_id) != (
            workspace.workspace_id,
            workspace.principal.user_id,
        ):
            raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
        return row
    content = item_content(item)
    row = VideoProjectRecord(
        id=project_id,
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        revision=1,
        content=content,
    )
    session.add(row)
    session.flush()
    append_version(session, project_id, content, "draft")
    session.commit()
    return row


def _write(session: Session, item: VideoWorkItemRecord, **values: Any) -> bool:
    if all(getattr(item, name) == value for name, value in values.items()):
        return False
    changed = session.execute(
        update(VideoWorkItemRecord)
        .where(
            VideoWorkItemRecord.id == item.id,
            VideoWorkItemRecord.version == item.version,
        )
        .values(**values, version=item.version + 1, updated_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    session.commit()
    if cast(CursorResult, changed).rowcount == 1:
        session.refresh(item)
        return True
    session.refresh(item)
    return False


def sync_items(session: Session, items: Iterable[VideoWorkItemRecord]) -> None:
    """Mirror each item's lipsync task into the item's status."""
    for item in items:
        if item.stage != "talking" or not item.generation_task_id:
            continue
        job = session.get(VideoGenerationRecord, item.generation_task_id)
        if job is None:
            continue
        status = GENERATION_TO_ITEM.get(job.status, "running")
        error = (
            ERROR_COPY.get(job.error_code or "", DEFAULT_ERROR)
            if status == "failed"
            else None
        )
        ref = (
            {"kind": "talking", "id": job.id}
            if status == "succeeded"
            else item.source_video_ref
        )
        _write(session, item, status=status, error=error, source_video_ref=ref)


def waiting(item: VideoWorkItemRecord) -> bool:
    """Confirmed by the user (queued) but not yet given a task.

    ``pending`` items were never confirmed: only the submit/retry POST turns
    them into ``queued``, so polling can never start a paid task by itself.
    """
    return (
        item.stage == "talking"
        and item.status == "queued"
        and not item.generation_task_id
    )


def confirm(session: Session, items: Iterable[VideoWorkItemRecord]) -> None:
    for item in items:
        if (
            item.stage == "talking"
            and item.status == "pending"
            and not item.generation_task_id
        ):
            _write(session, item, status="queued")


def _active_count(session: Session, user_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(VideoGenerationRecord)
            .where(
                VideoGenerationRecord.owner_user_id == user_id,
                VideoGenerationRecord.status.in_(ACTIVE_VIDEO_STATUSES),
            )
        )
        or 0
    )


def dispatch(
    session: Session,
    settings: Settings,
    workspace: WorkspaceContext,
    batch_id: str,
    provider: ProviderFactory,
) -> list[str]:
    """Start waiting items while the user has free slots; returns new task ids."""
    lock = _DispatchLock(session, workspace.principal.user_id)
    if not lock.acquire():
        return []  # Another request is dispatching this user's items right now.
    try:
        items = batch_items(session, batch_id)
        sync_items(session, items)
        slots = TALKING_PARALLEL - _active_count(session, workspace.principal.user_id)
        started: list[str] = []
        for item in items:
            if not waiting(item):
                continue
            if slots <= 0:
                _write(session, item, status="queued")
                continue
            try:
                if item.drive_mode == "text" and not item.voice_id:
                    raise ApiError(422, "VIDEO_VOICE_INVALID", "请先给这条稿选择音色。")
                if not item.avatar_id:
                    raise ApiError(
                        422, "VIDEO_AVATAR_NOT_FOUND", "请先给这条稿选择数字人。"
                    )
                project = ensure_project(session, workspace, item)
                body = GenerationRequest(
                    request_id=talking_request_id(item),
                    kind="lipsync",
                    avatar_id=item.avatar_id,
                    project_id=UUID(project.id),
                    expected_revision=project.revision,
                    audio_id=UUID(item.audio_file_id) if item.audio_file_id else None,
                )
                job, created = create_generation(
                    session, settings, workspace, body, provider
                )
            except ApiError as error:
                session.rollback()
                if error.status_code == 429:
                    # The user's overall video cap is full: wait for a free slot.
                    _write(session, item, status="queued")
                    slots = 0
                    continue
                # Anything else is specific to this item; the others carry on.
                logger.info("talking item %s not submitted: %s", item.id, error.code)
                _write(
                    session,
                    item,
                    status="failed",
                    error=ERROR_COPY.get(error.code, error.message),
                )
                continue
            _write(
                session,
                item,
                generation_task_id=job.id,
                status=GENERATION_TO_ITEM.get(job.status, "running"),
                error=None,
            )
            if created:
                started.append(job.id)
            if job.status in ACTIVE_VIDEO_STATUSES:
                slots -= 1
        return started
    finally:
        lock.release()


class _DispatchLock:
    """Per-user session lock on its own connection (create_generation commits)."""

    def __init__(self, session: Session, user_id: str) -> None:
        self.bind = session.get_bind()
        self.key = f"polaris:video-talking-dispatch:{user_id}"
        self.connection: Any = None

    def acquire(self) -> bool:
        if self.bind.dialect.name != "postgresql":
            return True
        self.connection = self.bind.connect()  # type: ignore[union-attr]
        got = self.connection.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:key))"), {"key": self.key}
        ).scalar()
        if not got:
            self.connection.close()
            self.connection = None
        return bool(got)

    def release(self) -> None:
        if self.connection is None:
            return
        try:
            self.connection.execute(
                text("SELECT pg_advisory_unlock(hashtext(:key))"), {"key": self.key}
            )
            self.connection.commit()
        finally:
            self.connection.close()
            self.connection = None


def _own_batch(
    session: Session, workspace: WorkspaceContext, batch_id: str
) -> VideoWorkBatchRecord:
    batch = session.get(VideoWorkBatchRecord, batch_id)
    if batch is None or (batch.workspace_id, batch.owner_user_id) != (
        workspace.workspace_id,
        workspace.principal.user_id,
    ):
        raise ApiError(404, "VIDEO_WORK_BATCH_NOT_FOUND", "未找到这个批次。")
    return batch


def _schedule(
    request: Request, background: BackgroundTasks, settings: Settings, ids: list[str]
) -> None:
    for job_id in ids:
        background.add_task(
            process_generation,
            request.app.state.session_factory,
            settings,
            job_id,
            providers(request),
        )


class TalkingItemView(StrictVideoModel):
    item_id: str
    queue_position: int | None = None
    stage: str | None = None
    video_url: str | None = None
    can_retry: bool = False


class TalkingBatchResponse(StrictVideoModel):
    batch: WorkBatchResponse
    talking: list[TalkingItemView]
    parallel_limit: int = TALKING_PARALLEL


def talking_view(session: Session, batch: VideoWorkBatchRecord) -> TalkingBatchResponse:
    items = batch_items(session, batch.id)
    views: list[TalkingItemView] = []
    position = 0
    base = f"/api/v1/video-studio/workspaces/{batch.workspace_id}/generation-tasks/"
    for item in items:
        view = TalkingItemView(item_id=item.id, can_retry=item.status == "failed")
        if waiting(item):
            position += 1
            view.queue_position = position
        if item.generation_task_id:
            job = session.get(VideoGenerationRecord, item.generation_task_id)
            if job is not None:
                view.stage = job.stage
                if job.status == "completed":
                    view.video_url = base + job.id + "/video"
        views.append(view)
    return TalkingBatchResponse(batch=batch_response(batch, items), talking=views)


@router.post("/work-batches/{batch_id}/talking", response_model=TalkingBatchResponse)
def submit_talking(
    batch_id: str,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> TalkingBatchResponse:
    """Submit (or keep submitting) every waiting item. Safe to call repeatedly."""
    require_workspace_write(workspace)
    batch = _own_batch(session, workspace, batch_id)
    if batch.source != "talking":
        raise ApiError(422, "VIDEO_WORK_BATCH_SOURCE", "这个批次不需要口播。")
    confirm(session, batch_items(session, batch.id))
    settings = request.app.state.settings
    started = dispatch(
        session, settings, workspace, batch.id, lambda: providers(request)
    )
    _schedule(request, background, settings, started)
    return talking_view(session, batch)


@router.get("/work-batches/{batch_id}/talking", response_model=TalkingBatchResponse)
def talking_status(
    batch_id: str,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> TalkingBatchResponse:
    """Polling view; also starts queued items whose turn has come."""
    batch = _own_batch(session, workspace, batch_id)
    items = batch_items(session, batch.id)
    if any(waiting(item) for item in items) and workspace.role != MembershipRole.VIEWER:
        settings = request.app.state.settings
        started = dispatch(
            session, settings, workspace, batch.id, lambda: providers(request)
        )
        _schedule(request, background, settings, started)
    else:
        sync_items(session, items)
    return talking_view(session, batch)


@router.post("/work-items/{item_id}/talking-retry", response_model=TalkingBatchResponse)
def retry_talking(
    item_id: str,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> TalkingBatchResponse:
    """Give one failed item a fresh attempt; the other items are untouched.

    Repeating the call is harmless: once the item is no longer failed the
    current view is returned and nothing new is submitted.
    """
    require_workspace_write(workspace)
    item = session.get(VideoWorkItemRecord, item_id)
    if item is None or (item.workspace_id, item.owner_user_id) != (
        workspace.workspace_id,
        workspace.principal.user_id,
    ):
        raise ApiError(404, "VIDEO_WORK_ITEM_NOT_FOUND", "未找到这条作品。")
    batch = _own_batch(session, workspace, item.batch_id)
    if item.stage != "talking":
        raise ApiError(
            409, "VIDEO_WORK_ITEM_STAGE", "这条已经进入下一步，不能重新口播。"
        )
    sync_items(session, [item])
    if item.status == "failed":
        history = {key: list(value) for key, value in (item.history or {}).items()}
        # Failed before a task existed: still count the attempt, so the next
        # request id is new.
        history.setdefault("generation", []).append(
            item.generation_task_id or f"none:{attempt(item)}"
        )
        _write(
            session,
            item,
            generation_task_id=None,
            status="queued",
            error=None,
            history=history,
        )
    settings = request.app.state.settings
    started = dispatch(
        session, settings, workspace, batch.id, lambda: providers(request)
    )
    _schedule(request, background, settings, started)
    return talking_view(session, batch)


def continue_after(
    factory: sessionmaker[Session],
    settings: Settings,
    job_id: str,
    provider: VideoProviders,
) -> None:
    """After a lipsync task ends, start the next waiting item of its batch."""
    try:
        with factory() as session:
            item = session.scalar(
                select(VideoWorkItemRecord).where(
                    VideoWorkItemRecord.generation_task_id == job_id
                )
            )
            if item is None:
                return
            member = session.scalar(
                select(WorkspaceMemberRecord).where(
                    WorkspaceMemberRecord.workspace_id == item.workspace_id,
                    WorkspaceMemberRecord.user_id == item.owner_user_id,
                    WorkspaceMemberRecord.status == MembershipStatus.ACTIVE.value,
                )
            )
            if member is None or member.role == MembershipRole.VIEWER.value:
                return
            workspace = WorkspaceContext(
                principal=Principal(user_id=item.owner_user_id),
                workspace_id=item.workspace_id,
                role=MembershipRole(member.role),
            )
            started = dispatch(
                session, settings, workspace, item.batch_id, lambda: provider
            )
        for started_id in started:
            if settings.task_dispatcher == "inline":
                process_generation(factory, settings, started_id, provider)
                continue
            Thread(
                target=process_generation,
                args=(factory, settings, started_id, provider),
                daemon=True,
                name=f"video-talking-{started_id[:8]}",
            ).start()
    except Exception:  # Never break the finished task; recovery picks up queued work.
        logger.exception("talking batch continuation failed after %s", job_id)
