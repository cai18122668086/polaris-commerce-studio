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
from datetime import UTC, timedelta
from threading import Event, Thread
from typing import Any, cast
from uuid import UUID, uuid5

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from . import video_credit_billing as video_credits
from .auth import (
    Principal,
    SessionDependency,
    WorkspaceContext,
    require_workspace_write,
)
from .config import Settings
from .domain import MembershipRole, MembershipStatus
from .errors import ApiError
from .models import WorkspaceCreditAccountRecord, WorkspaceMemberRecord, utc_now
from .services import credit_enforcement_enabled
from .video_dispatch_lock import DispatchLock
from .video_generation import (
    ACTIVE_VIDEO_STATUSES,
    GenerationRequest,
    create_generation,
    job_response,
    own_job,
    process_generation,
    providers,
)
from .video_generation_models import VideoGenerationRecord, VideoGenerationRunRecord
from .video_generation_runtime import VideoRunLease, acquire_run
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
    "VIDEO_PROVIDER_OUTCOME_EXPIRED": (
        "这条的提交结果超过 24 小时仍无法确认，已按失败处理，冻结的积分已退回；"
        "如需核对请联系客服。"
    ),
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


def confirm(
    session: Session,
    settings: Settings,
    workspace_id: str,
    items: Iterable[VideoWorkItemRecord],
) -> None:
    """The user confirmed: check the whole batch can be paid, then queue it.

    Credits are held per item when its task is created (the existing
    per-task hold), but the balance is checked here for every item about to
    run, so a batch is either accepted as a whole or refused as a whole.
    """
    items = list(items)
    fresh = [
        item
        for item in items
        if item.stage == "talking"
        and item.status == "pending"
        and not item.generation_task_id
        and item.deleted_at is None  # 从我的作品删掉的条目不再生成
    ]
    waiting_now = [item for item in items if waiting(item)]
    check_batch_credits(session, settings, workspace_id, len(fresh) + len(waiting_now))
    for item in fresh:
        _write(session, item, status="queued")


def check_batch_credits(
    session: Session, settings: Settings, workspace_id: str, count: int
) -> None:
    price = video_credits.price_for(settings, "lipsync")
    if not count or price is None or not credit_enforcement_enabled(workspace_id):
        return
    account = session.get(WorkspaceCreditAccountRecord, workspace_id)
    if account is None:
        raise ApiError(409, "CREDIT_ACCOUNT_NOT_CONFIGURED", "工作区额度账户尚未配置。")
    from .credit_memberships import refresh

    account = refresh(session, workspace_id)
    available = max(0, account.balance_credits - account.reserved_credits)
    session.commit()
    required = price * count
    if available < required:
        raise ApiError(
            402,
            "BUDGET_LIMIT_EXCEEDED",
            f"{count} 条口播需要 {required} 积分，当前可用 {available} 积分，"
            "请充值或减少条数后再生成。",
            {"required_credits": required, "available_credits": available},
        )


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
    lock = DispatchLock(session, "talking", workspace.principal.user_id)
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
    # The paid submission's outcome is unknown: shown as 结果待确认 with a
    # 查询结果 button; never re-submitted automatically.
    awaiting_check: bool = False
    # The provider is slow (awaiting_resume): the sweep keeps querying it on a
    # backoff; 查询结果 asks now. Never re-submitted.
    long_wait: bool = False
    # Why a failed item failed (the lipsync task's error code), so the result
    # box can explain special cases such as VIDEO_PROVIDER_OUTCOME_EXPIRED.
    error_code: str | None = None


class TalkingBatchResponse(StrictVideoModel):
    batch: WorkBatchResponse
    talking: list[TalkingItemView]
    parallel_limit: int = TALKING_PARALLEL
    notice: str | None = None


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
                view.awaiting_check = job.status == "unknown"
                view.long_wait = job.status == "awaiting_resume"
                if job.status == "completed":
                    view.video_url = base + job.id + "/video"
                if item.status == "failed":
                    view.error_code = job.error_code
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
    settings = request.app.state.settings
    confirm(session, settings, batch.workspace_id, batch_items(session, batch.id))
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
    if (
        item is None
        or item.deleted_at is not None
        or (item.workspace_id, item.owner_user_id)
        != (
            workspace.workspace_id,
            workspace.principal.user_id,
        )
    ):
        raise ApiError(404, "VIDEO_WORK_ITEM_NOT_FOUND", "未找到这条作品。")
    batch = _own_batch(session, workspace, item.batch_id)
    if item.stage != "talking":
        raise ApiError(
            409, "VIDEO_WORK_ITEM_STAGE", "这条已经进入下一步，不能重新口播。"
        )
    sync_items(session, [item])
    settings = request.app.state.settings
    if item.status == "failed":
        check_batch_credits(session, settings, item.workspace_id, 1)
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
    started = dispatch(
        session, settings, workspace, batch.id, lambda: providers(request)
    )
    _schedule(request, background, settings, started)
    return talking_view(session, batch)


def _workspace_for(
    session: Session, workspace_id: str, owner_user_id: str
) -> WorkspaceContext | None:
    member = session.scalar(
        select(WorkspaceMemberRecord).where(
            WorkspaceMemberRecord.workspace_id == workspace_id,
            WorkspaceMemberRecord.user_id == owner_user_id,
            WorkspaceMemberRecord.status == MembershipStatus.ACTIVE.value,
        )
    )
    if member is None or member.role == MembershipRole.VIEWER.value:
        return None
    return WorkspaceContext(
        principal=Principal(user_id=owner_user_id),
        workspace_id=workspace_id,
        role=MembershipRole(member.role),
    )


def advance(
    factory: sessionmaker[Session],
    settings: Settings,
    provider: VideoProviders,
    batch_id: str,
) -> list[str]:
    """Sync one batch and start its waiting items; returns new task ids."""
    with factory() as session:
        batch = session.get(VideoWorkBatchRecord, batch_id)
        if batch is None:
            return []
        workspace = _workspace_for(session, batch.workspace_id, batch.owner_user_id)
        if workspace is None:
            sync_items(session, batch_items(session, batch_id))
            return []
        return dispatch(session, settings, workspace, batch_id, lambda: provider)


def run_tasks(
    factory: sessionmaker[Session],
    settings: Settings,
    provider: VideoProviders,
    job_ids: Iterable[str],
) -> None:
    for job_id in job_ids:
        if settings.task_dispatcher == "inline":
            process_generation(factory, settings, job_id, provider)
            continue
        Thread(
            target=process_generation,
            args=(factory, settings, job_id, provider),
            daemon=True,
            name=f"video-talking-{job_id[:8]}",
        ).start()


def continue_after(
    factory: sessionmaker[Session],
    settings: Settings,
    job_id: str,
    provider: VideoProviders,
) -> None:
    """After a lipsync task ends, start the next waiting item of its batch."""
    try:
        with factory() as session:
            batch_id = session.scalar(
                select(VideoWorkItemRecord.batch_id).where(
                    VideoWorkItemRecord.generation_task_id == job_id
                )
            )
        if batch_id is None:
            return
        run_tasks(
            factory, settings, provider, advance(factory, settings, provider, batch_id)
        )
    except Exception:  # Never break the finished task; the sweep retries later.
        logger.exception("talking batch continuation failed after %s", job_id)


ORPHAN_AFTER_SECONDS = 30


def sweep_once(
    factory: sessionmaker[Session], settings: Settings, provider: VideoProviders
) -> list[str]:
    """Restart safety net, independent of the general video recovery scanner.

    1. Batches with confirmed-but-unstarted items, or items whose task is still
       open, are synced and dispatched (an api restart drops the in-process
       "start the next one" chain).
    2. Tasks this module created that are still ``queued`` with no live lease
       (their request's background run died with the process) are started.
       The run lease guarantees a task is never processed twice.
    Returns the task ids it started.
    """
    expire_unconfirmed(factory)
    with factory() as session:
        # C8: most recently updated first (GROUP BY, not DISTINCT: PostgreSQL
        # requires ORDER BY expressions of a DISTINCT query in its select list).
        batch_ids = session.scalars(
            select(VideoWorkItemRecord.batch_id)
            .where(
                VideoWorkItemRecord.stage == "talking",
                VideoWorkItemRecord.status.in_(["queued", "running"]),
            )
            .group_by(VideoWorkItemRecord.batch_id)
            .order_by(func.max(VideoWorkItemRecord.updated_at).desc())
            .limit(50)
        ).all()
    started: list[str] = []
    for batch_id in batch_ids:
        try:
            started += advance(factory, settings, provider, batch_id)
        except Exception:
            logger.exception("talking sweep deferred batch %s", batch_id)
    cutoff = utc_now() - timedelta(seconds=ORPHAN_AFTER_SECONDS)
    with factory() as session:
        # B7: every generation task (avatar motions, single talking videos),
        # not only batch items; the run lease still starts each one once.
        orphans = session.scalars(
            select(VideoGenerationRecord.id)
            .where(
                VideoGenerationRecord.status == "queued",
                VideoGenerationRecord.created_at <= cutoff,
            )
            .order_by(VideoGenerationRecord.created_at, VideoGenerationRecord.id)
            .limit(20)
        ).all()
    leased: list[tuple[str, VideoRunLease]] = []
    leased += recover_stale_running(factory, settings)
    for job_id in orphans:
        if job_id in started:
            continue
        lease = acquire_run(factory, settings, job_id)
        if lease is not None:
            leased.append((job_id, lease))
    run_tasks(factory, settings, provider, started)
    for job_id, lease in leased:
        if settings.task_dispatcher == "inline":
            process_generation(factory, settings, job_id, provider, lease=lease)
            continue
        Thread(
            target=process_generation,
            args=(factory, settings, job_id, provider),
            kwargs={"lease": lease},
            daemon=True,
            name=f"video-talking-{job_id[:8]}",
        ).start()
    return started + [job_id for job_id, _ in leased]


STALE_RUNNING_SECONDS = 180
# C8: 结果待确认 (unknown) longer than this is settled as failed and its hold
# released, so it neither spins forever nor stays in every sweep.
UNCONFIRMED_EXPIRE_SECONDS = 24 * 3600
UNCONFIRMED_EXPIRED = "VIDEO_PROVIDER_OUTCOME_EXPIRED"
CHECK_NOTICE = (
    "这条的提交结果还在确认：不会重新生成，也不会重复扣积分。"
    "系统会继续核对，长时间没有结果请联系客服。"
)


def expire_unconfirmed(factory: sessionmaker[Session]) -> list[str]:
    """Fail generation tasks whose outcome stayed unknown for 24 hours.

    Any task (batch or not). The hold is released through the normal
    reconciliation; batch items are synced so the page shows the reason.
    """
    cutoff = utc_now() - timedelta(seconds=UNCONFIRMED_EXPIRE_SECONDS)
    with factory() as session:
        ids = session.scalars(
            select(VideoGenerationRecord.id)
            .where(
                VideoGenerationRecord.status == "unknown",
                VideoGenerationRecord.updated_at <= cutoff,
            )
            .order_by(VideoGenerationRecord.updated_at, VideoGenerationRecord.id)
            .limit(50)
        ).all()
        expired: list[str] = []
        for job_id in ids:
            changed = session.execute(
                update(VideoGenerationRecord)
                .where(
                    VideoGenerationRecord.id == job_id,
                    VideoGenerationRecord.status == "unknown",
                )
                .values(status="failed", error_code=UNCONFIRMED_EXPIRED)
                .execution_options(synchronize_session=False)
            )
            if cast(CursorResult, changed).rowcount == 1:
                expired.append(job_id)
        session.commit()
        if not expired:
            return []
        for job_id in expired:
            video_credits.reconcile_owner(session, "video_generation", job_id)
        session.commit()
        sync_items(
            session,
            session.scalars(
                select(VideoWorkItemRecord).where(
                    VideoWorkItemRecord.generation_task_id.in_(expired)
                )
            ).all(),
        )
    logger.warning("video tasks unconfirmed for 24h marked failed: %s", expired)
    return expired


def _take_over(
    factory: sessionmaker[Session], settings: Settings, job_id: str, *, stale_only: bool
) -> tuple[str, VideoRunLease] | None:
    """Continue one batch task whose run was lost, without ever re-submitting.

    Same rules as the general recovery scanner, for batch tasks only: a task
    whose provider job id is known (or that has not reached a paid submission)
    continues and only *queries* the provider; a task that may have been
    submitted but has no provider id is marked unknown (结果待确认) instead.
    Returns the lease when the task should be run.
    """
    from .video_generation_recovery import eligible  # noqa: PLC0415 (import cycle)
    from .video_generation_runtime import owner_can_run, unconfirmed_paid_submission

    lease = acquire_run(factory, settings, job_id)
    if lease is None:
        return None  # Someone still owns it: not lost.
    try:
        with factory() as session:
            job = session.get(VideoGenerationRecord, job_id)
            cutoff = utc_now() - timedelta(seconds=STALE_RUNNING_SECONDS)
            updated = job.updated_at if job else None
            if updated is not None and updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            if (
                job is None
                or job.status not in {"running", "unknown", "awaiting_resume"}
                or (
                    stale_only
                    and job.status == "running"
                    and updated
                    and updated > cutoff
                )
                or not owner_can_run(session, job)
            ):
                lease.release()
                return None
            if not eligible(job, settings):
                if job.status == "running" or unconfirmed_paid_submission(
                    job, settings
                ):
                    job.status, job.error_code = (
                        "unknown",
                        "VIDEO_PROVIDER_OUTCOME_UNKNOWN",
                    )
                session.commit()
                lease.release()
                return None
            changed = session.execute(
                update(VideoGenerationRecord)
                .where(
                    VideoGenerationRecord.id == job_id,
                    VideoGenerationRecord.status == job.status,
                )
                .values(status="queued")
            )
            session.commit()
            if cast(CursorResult, changed).rowcount != 1:
                lease.release()
                return None
        return job_id, lease
    except Exception:
        lease.release()
        raise


def recover_stale_running(
    factory: sessionmaker[Session], settings: Settings
) -> list[tuple[str, VideoRunLease]]:
    """Generation tasks still ``running`` 3+ minutes after their last
    heartbeat, and ``awaiting_resume`` ones whose retry time has come.

    The general recovery scanner is off in production, so a deploy restart
    would otherwise leave these spinning forever. Since B7 this covers every
    generation task (avatar motions, single talking videos), not only batch
    items: the rules stay the same (query only, never re-submit; see
    ``_take_over``), oldest first so a long backlog is not starved.
    """
    cutoff = utc_now() - timedelta(seconds=STALE_RUNNING_SECONDS)
    with factory() as session:
        ids = list(
            session.scalars(
                select(VideoGenerationRecord.id)
                .where(
                    VideoGenerationRecord.status == "running",
                    VideoGenerationRecord.updated_at <= cutoff,
                )
                .order_by(VideoGenerationRecord.updated_at, VideoGenerationRecord.id)
                .limit(20)
            ).all()
        )
    # Long provider waits park as awaiting_resume with a durable backoff; the
    # general scanner (off in production) would query again when it is due.
    now = utc_now()
    with factory() as session:
        ids += session.scalars(
            select(VideoGenerationRecord.id)
            .outerjoin(
                VideoGenerationRunRecord,
                VideoGenerationRunRecord.job_id == VideoGenerationRecord.id,
            )
            .where(
                VideoGenerationRecord.status == "awaiting_resume",
                or_(
                    VideoGenerationRunRecord.retry_at.is_(None),
                    VideoGenerationRunRecord.retry_at <= now,
                ),
            )
            .order_by(VideoGenerationRecord.updated_at, VideoGenerationRecord.id)
            .limit(20)
        ).all()
    taken: list[tuple[str, VideoRunLease]] = []
    for job_id in ids:
        try:
            result = _take_over(factory, settings, job_id, stale_only=True)
        except Exception:
            logger.exception("talking stale task %s deferred", job_id)
            continue
        if result:
            taken.append(result)
    return taken


@router.post("/work-items/{item_id}/talking-check", response_model=TalkingBatchResponse)
def check_talking(
    item_id: str,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> TalkingBatchResponse:
    """查询结果: query the provider for an unknown outcome. Never re-submits."""
    require_workspace_write(workspace)
    item = session.get(VideoWorkItemRecord, item_id)
    if item is None or (item.workspace_id, item.owner_user_id) != (
        workspace.workspace_id,
        workspace.principal.user_id,
    ):
        raise ApiError(404, "VIDEO_WORK_ITEM_NOT_FOUND", "未找到这条作品。")
    batch = _own_batch(session, workspace, item.batch_id)
    job = (
        session.get(VideoGenerationRecord, item.generation_task_id)
        if item.generation_task_id
        else None
    )
    notice = None
    if job is not None and job.status in {"unknown", "running", "awaiting_resume"}:
        settings = request.app.state.settings
        session.commit()
        taken = _take_over(
            request.app.state.session_factory, settings, job.id, stale_only=True
        )
        if taken:
            job_id, lease = taken
            background.add_task(
                process_generation,
                request.app.state.session_factory,
                settings,
                job_id,
                providers(request),
                lease=lease,
            )
        else:
            session.expire_all()
            fresh = session.get(VideoGenerationRecord, job.id)
            if fresh is not None and fresh.status == "unknown":
                notice = CHECK_NOTICE
    sync_items(session, batch_items(session, batch.id))
    view = talking_view(session, batch)
    view.notice = notice
    return view


@router.post("/generation-tasks/{job_id}/check")
def check_generation(
    job_id: UUID,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    """查询结果 for any generation task (e.g. an avatar motion in the library).

    Same rules as ``talking-check``: a task whose run was lost continues and
    only queries the provider; an unknown outcome without a provider id stays
    结果待确认 with ``notice``. Never re-submits, never charges again.
    """
    require_workspace_write(workspace)
    job = own_job(session, workspace, job_id)
    notice = None
    if job.status in {"unknown", "running", "awaiting_resume"}:
        settings = request.app.state.settings
        session.commit()
        taken = _take_over(
            request.app.state.session_factory, settings, job.id, stale_only=True
        )
        if taken:
            taken_id, lease = taken
            background.add_task(
                process_generation,
                request.app.state.session_factory,
                settings,
                taken_id,
                providers(request),
                lease=lease,
            )
        session.expire_all()
        job = own_job(session, workspace, job_id)
        if job.status == "unknown":
            notice = CHECK_NOTICE
    return {**job_response(job), "notice": notice}


class TalkingSweeper:
    """Runs ``sweep_once`` every few seconds inside the API process."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        settings: Settings,
        provider: VideoProviders,
    ) -> None:
        self.factory, self.settings, self.provider = factory, settings, provider
        self.stopped = Event()
        self.thread: Thread | None = None

    def run(self) -> None:
        # First pass right after startup: that is when a restart left work behind.
        while not self.stopped.is_set():
            try:
                sweep_once(self.factory, self.settings, self.provider)
            except Exception:
                logger.warning("talking sweep deferred after an error", exc_info=True)
            self.stopped.wait(self.settings.video_recovery_interval_seconds)

    def start(self) -> None:
        self.thread = Thread(target=self.run, daemon=True, name="video-talking-sweep")
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)
