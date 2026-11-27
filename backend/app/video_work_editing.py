"""Editing stage for work batches (W3): batch editing with a per-user queue.

Each work item gets its own pipeline, entirely server side:

    recognition -> free check -> paid planning -> render -> automatic export

The user confirms the batch once (template, music, supplement per item). Every
task the pipeline creates uses a request id derived from the item, its attempt
and the step, and every step first looks for the task it would create, so a
lost response, a reload, a second tab or an API restart never creates or
charges for a second task. At most ``EDITING_PARALLEL`` items per user are in
the pipeline at once; the rest wait with a queue position. The site has one
shared editing worker, so the queue estimate counts every user's work.

Tasks are only persisted here; the editing maintenance service delivers queued
editing and planning tasks to the worker (the durable outbox), as before.
"""

from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Any, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from . import video_credit_billing as video_credits
from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .config import Settings
from .errors import ApiError
from .models import WorkspaceCreditAccountRecord
from .services import credit_enforcement_enabled
from .video_editing_contracts import (
    EditingOptions,
    EditingPlanningTaskCreate,
    EditingSupplementOptions,
    EditingTaskCreate,
)
from .video_editing_planning_preview import persist_planning_preview
from .video_editing_planning_store import (
    create_planning_task,
    planning_response,
    require_active_planning_template,
    same_request_generate,
)
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingPlanningTaskRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)
from .video_editing_task_routes import confirm_export_task, persist_editing_task
from .video_generation_models import VideoGenerationRecord
from .video_studio_access import require_video_studio_access
from .video_studio_routes import VideoWorkspace
from .video_studio_schemas import StrictVideoModel
from .video_work_editing_models import ACTIVE_PHASES, VideoWorkEditingRunRecord
from .video_work_models import VideoWorkBatchRecord, VideoWorkItemRecord
from .video_work_routes import WorkBatchResponse, batch_items, batch_response
from .video_work_talking import _workspace_for, _write

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-work"],
    dependencies=[Depends(require_video_studio_access)],
)

EDITING_PARALLEL = 2
# One item through recognition, planning, render and export on the shared
# worker, measured on dev (8 cores, worker concurrency 1): about 6 minutes.
MINUTES_PER_ITEM = 6
NAMESPACE = UUID("0b7c2f4e-3a59-4d8e-9c61-5e2a8f7d4b30")
MusicChoice = Literal["template", "lower", "raise", "off"]

FAILURE_COPY = {
    "EDITING_NO_SPEECH_RECOGNIZED": "没有识别到清晰的口播声音，请换一条视频。",
    "EDITING_ORIENTATION_REVIEW_REQUIRED": (
        "这个模板需要竖屏 9:16 的视频，这条画幅不符，可换模板或换视频。"
    ),
    "EDITING_TEMPLATE_GROUPS_INSUFFICIENT": (
        "这条口播配这个模板可用的动效太少，换一个模板试试。"
    ),
    "EDITING_PLAN_EMPTY_RESPONSE": "画面编排这次没有返回内容，未扣编排费，可以重试。",
    "EDITING_PLAN_CONTRACT_INVALID": "画面编排没有通过检查，可以免费重试。",
    "EDITING_TRANSCRIPT_REVIEW_REQUIRED": (
        "识别出的字幕和口播稿差别较大，请到「精修这一条」里校对字幕后再剪。"
    ),
    "BUDGET_LIMIT_EXCEEDED": "积分不足，充值后点重试。",
    "EDITING_PLANNING_DISABLED": "自动剪辑暂未开放，请稍后再试。",
}
STEP_COPY = {
    "transcribing": "口播识别没有完成，可以重试。",
    "preparing": "素材检查没有通过，可以换模板或重试。",
    "planning": "画面编排没有完成，可以重试。",
    "rendering": "视频生成中断，可以免费重试，不会重复扣编排费。",
}


# --------------------------------------------------------------------------- API models


class EditingItemChoice(StrictVideoModel):
    template_id: str | None = Field(default=None, min_length=1, max_length=64)
    material_ids: list[UUID] = Field(default_factory=list, max_length=24)
    supplement: EditingSupplementOptions | None = None


class EditingBatchSubmit(StrictVideoModel):
    request_id: UUID
    template_id: str = Field(min_length=1, max_length=64)
    music: MusicChoice = "template"
    # Only these items (default: every item with a finished source video).
    item_ids: list[str] | None = Field(default=None, max_length=20)
    # Per item: its own template, materials and supplement (C5).
    items: dict[str, EditingItemChoice] = Field(default_factory=dict)


class EditingItemView(StrictVideoModel):
    item_id: str
    position: int
    phase: str | None = None
    template_id: str | None = None
    queue_position: int | None = None
    estimate_minutes: int | None = None
    error: str | None = None
    can_retry: bool = False
    render_task_id: str | None = None
    project_id: str | None = None
    final_url: str | None = None
    poster_url: str | None = None
    duration_ms: int | None = None
    # Not editable yet: the talking video is not finished (or failed).
    waiting_for_source: bool = False


class EditingBatchResponse(StrictVideoModel):
    batch: WorkBatchResponse
    editing: list[EditingItemView]
    parallel_limit: int = EDITING_PARALLEL
    notice: str | None = None


class EditingSourceView(StrictVideoModel):
    id: str
    project_id: str
    created_at: Any
    video_url: str
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    file_name: str | None = None


# --------------------------------------------------------------------------- helpers


def _request_id(run: VideoWorkEditingRunRecord, step: str) -> UUID:
    return uuid5(NAMESPACE, f"{run.item_id}:{run.attempt}:{step}")


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


def _own_item(
    session: Session, workspace: WorkspaceContext, item_id: str
) -> VideoWorkItemRecord:
    item = session.get(VideoWorkItemRecord, item_id)
    if item is None or (item.workspace_id, item.owner_user_id) != (
        workspace.workspace_id,
        workspace.principal.user_id,
    ):
        raise ApiError(404, "VIDEO_WORK_ITEM_NOT_FOUND", "未找到这条作品。")
    return item


def source_ready(item: VideoWorkItemRecord) -> bool:
    """The item has a finished video to edit."""
    ref = item.source_video_ref or {}
    if not ref.get("id"):
        return False
    if ref.get("kind") == "talking":
        return item.stage != "talking" or item.status == "succeeded"
    return True


def _source_body(
    session: Session, workspace: WorkspaceContext, item: VideoWorkItemRecord
) -> dict[str, UUID]:
    """Talking/library generation -> generation_task_id; uploads -> source_id."""
    ref = item.source_video_ref or {}
    ident = str(ref.get("id") or "")
    if ref.get("kind") in {"talking", "library"}:
        job = session.get(VideoGenerationRecord, ident)
        if job is not None:
            if (job.workspace_id, job.owner_user_id) != (
                workspace.workspace_id,
                workspace.principal.user_id,
            ) or job.status != "completed":
                raise ApiError(
                    409, "VIDEO_WORK_SOURCE_NOT_READY", "这条口播视频还没有生成完成。"
                )
            return {"generation_task_id": UUID(job.id)}
    source = session.get(EditingSourceRecord, ident)
    if source is None or (source.workspace_id, source.owner_user_id) != (
        workspace.workspace_id,
        workspace.principal.user_id,
    ):
        raise ApiError(404, "EDITING_SOURCE_NOT_FOUND", "未找到这条视频，请重新选择。")
    return {"source_id": UUID(source.id)}


def _fail(
    session: Session,
    run: VideoWorkEditingRunRecord,
    item: VideoWorkItemRecord,
    code: str | None,
    step: str,
) -> None:
    message = FAILURE_COPY.get(code or "") or STEP_COPY.get(
        step, "这条没有剪成功，可以重试。"
    )
    run.phase, run.error_code, run.error = "failed", code, message
    session.commit()
    _write(session, item, stage="editing", status="failed", error=message)


def _by_request(
    session: Session, model: Any, run: VideoWorkEditingRunRecord, request_id: UUID
) -> Any:
    return session.scalar(
        select(model).where(
            model.workspace_id == run.workspace_id,
            model.owner_user_id == run.owner_user_id,
            model.request_id == str(request_id),
        )
    )


# --------------------------------------------------------------------------- pipeline


def _start_transcript(
    session: Session,
    settings: Settings,
    workspace: WorkspaceContext,
    run: VideoWorkEditingRunRecord,
    item: VideoWorkItemRecord,
) -> None:
    request_id = _request_id(run, "transcript")
    row = _by_request(session, EditingTaskRecord, run, request_id)
    if row is None:
        body = EditingTaskCreate(
            request_id=request_id,
            **_source_body(session, workspace, item),
            options=EditingOptions(mode="transcript", source_subtitles="none"),
        )
        row, _ = persist_editing_task(body, settings, workspace, session)
    run.transcript_task_id, run.phase = row.id, "transcribing"
    session.commit()
    _write(session, item, stage="editing", status="running", error=None)


def _step(
    session: Session,
    settings: Settings,
    workspace: WorkspaceContext,
    run: VideoWorkEditingRunRecord,
    item: VideoWorkItemRecord,
) -> None:
    """Move one active run forward by at most one step (never pays twice)."""
    if run.phase == "transcribing":
        base = session.get(EditingTaskRecord, run.transcript_task_id)
        if base is None or base.status in {"failed", "cancelled"}:
            _fail(session, run, item, base.error_code if base else None, run.phase)
        elif base.status == "completed":
            choice = run.options or {}
            request_id = _request_id(run, "prepare")
            prepared = _by_request(session, EditingPlanningTaskRecord, run, request_id)
            if prepared is None:
                body = EditingPlanningTaskCreate(
                    request_id=request_id,
                    mode="prepare",
                    template_id=run.template_id,
                    music=choice.get("music") or "template",
                    material_ids=[
                        UUID(value) for value in choice.get("material_ids") or []
                    ]
                    or None,
                    supplement=EditingSupplementOptions.model_validate(
                        choice["supplement"]
                    )
                    if choice.get("supplement")
                    else None,
                )
                prepared = create_planning_task(
                    session, workspace, base, body, settings
                )
            run.prepare_task_id, run.phase = prepared.id, "preparing"
            session.commit()
        return
    if run.phase == "preparing":
        prepared = session.get(EditingPlanningTaskRecord, run.prepare_task_id)
        if prepared is None or prepared.status in {"failed", "cancelled"}:
            _fail(
                session, run, item, prepared.error_code if prepared else None, run.phase
            )
            return
        if prepared.status != "prepared":
            return
        view = planning_response(prepared, settings)
        if not view["execution_available"]:
            _fail(session, run, item, "EDITING_PLANNING_DISABLED", run.phase)
            return
        blockers = view.get("template_style_blockers") or []
        if blockers or (view.get("available_template_group_count") or 1) < 1:
            run.phase, run.error_code = "failed", "EDITING_TEMPLATE_GROUPS_INSUFFICIENT"
            run.error = (
                f"这个模板需要的素材还不够：{blockers[0]}"
                if blockers and isinstance(blockers[0], str)
                else FAILURE_COPY["EDITING_TEMPLATE_GROUPS_INSUFFICIENT"]
            )
            session.commit()
            _write(session, item, stage="editing", status="failed", error=run.error)
            return
        request_id = _request_id(run, "generate")
        generated = _by_request(session, EditingPlanningTaskRecord, run, request_id)
        if generated is None:
            base = session.get(EditingTaskRecord, prepared.base_task_id)
            assert base is not None
            body = EditingPlanningTaskCreate(
                request_id=request_id,
                mode="generate",
                prepared_task_id=UUID(prepared.id),
                auto_preview=bool(view["auto_preview_available"]),
            )
            try:
                generated = create_planning_task(
                    session, workspace, base, body, settings
                )
            except ApiError as error:
                session.rollback()
                if error.code != "EDITING_PLAN_ALREADY_GENERATED":
                    raise
                # The same request already has a live or finished planning
                # (e.g. the user ran it on the old page): join it, pay nothing.
                generated = same_request_generate(session, workspace, prepared)
                if generated is None:
                    raise
        run.generate_task_id, run.phase = generated.id, "planning"
        session.commit()
        return
    if run.phase == "planning":
        generated = session.get(EditingPlanningTaskRecord, run.generate_task_id)
        if generated is None or generated.status in {"failed", "cancelled"}:
            _fail(
                session,
                run,
                item,
                generated.error_code if generated else None,
                run.phase,
            )
            return
        if generated.status != "completed":
            return
        preview_id = generated.result.get("preview_task_id")
        if not preview_id:
            waiting_auto = generated.checkpoint.get(
                "auto_preview"
            ) and not generated.result.get("auto_preview_error_code")
            if waiting_auto:
                return  # The worker links the automatic preview itself.
            linked, _ = persist_planning_preview(
                generated, workspace, session, settings
            )
            preview_id = linked.id
        run.render_task_id, run.phase = preview_id, "rendering"
        session.commit()
        _write(session, item, editing_task_id=preview_id)
        return
    if run.phase == "rendering":
        task = session.get(EditingTaskRecord, run.render_task_id)
        if task is None or task.status in {"failed", "cancelled"}:
            _fail(session, run, item, task.error_code if task else None, run.phase)
            return
        if task.status == "awaiting_review":
            preview = session.scalar(
                select(EditingArtifactRecord).where(
                    EditingArtifactRecord.task_id == task.id,
                    EditingArtifactRecord.role == "preview",
                )
            )
            if preview is None:
                return
            # Batch editing confirms by default: the preview and the export are
            # the same render, confirming is free, and the result box keeps
            # 「精修这一条」 and re-planning for anything the user dislikes.
            task = confirm_export_task(
                session, settings, workspace, task, preview.id, preview.sha256
            )
        if task.status == "completed":
            run.phase, run.error, run.error_code = "done", None, None
            session.commit()
            _write(
                session,
                item,
                editing_task_id=task.id,
                stage="finishing",
                status="pending",
                error=None,
            )


def _active_count(session: Session, user_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(VideoWorkEditingRunRecord)
            .where(
                VideoWorkEditingRunRecord.owner_user_id == user_id,
                VideoWorkEditingRunRecord.phase.in_(ACTIVE_PHASES),
            )
        )
        or 0
    )


def dispatch(
    session: Session, settings: Settings, workspace: WorkspaceContext, batch_id: str
) -> None:
    """Advance the batch's active runs, then start waiting ones while slots last."""
    runs = {
        run.item_id: run
        for run in session.scalars(
            select(VideoWorkEditingRunRecord).where(
                VideoWorkEditingRunRecord.batch_id == batch_id
            )
        )
    }
    items = batch_items(session, batch_id)
    for item in items:
        run = runs.get(item.id)
        if run is None or run.phase not in ACTIVE_PHASES:
            continue
        try:
            _step(session, settings, workspace, run, item)
        except ApiError as error:
            session.rollback()
            session.refresh(run)
            logger.info("editing item %s stopped: %s", item.id, error.code)
            _fail(session, run, item, error.code, run.phase)
        except Exception:
            # Unexpected: leave the step as it is; the sweep tries again.
            session.rollback()
            logger.exception("editing item %s step deferred", item.id)
    slots = EDITING_PARALLEL - _active_count(session, workspace.principal.user_id)
    for item in items:
        run = runs.get(item.id)
        if run is None or run.phase != "queued" or slots <= 0:
            continue
        try:
            _start_transcript(session, settings, workspace, run, item)
            slots -= 1
        except ApiError as error:
            session.rollback()
            session.refresh(run)
            _fail(session, run, item, error.code, "transcribing")


# --------------------------------------------------------------------------- views


def _global_ahead(session: Session, run: VideoWorkEditingRunRecord) -> int:
    """Items of every user ahead of this one on the single shared worker."""
    active = session.scalar(
        select(func.count())
        .select_from(VideoWorkEditingRunRecord)
        .where(VideoWorkEditingRunRecord.phase.in_(ACTIVE_PHASES))
    )
    earlier = session.scalar(
        select(func.count())
        .select_from(VideoWorkEditingRunRecord)
        .where(
            VideoWorkEditingRunRecord.phase == "queued",
            VideoWorkEditingRunRecord.created_at < run.created_at,
        )
    )
    return int(active or 0) + int(earlier or 0)


def editing_view(session: Session, batch: VideoWorkBatchRecord) -> EditingBatchResponse:
    items = batch_items(session, batch.id)
    runs = {
        run.item_id: run
        for run in session.scalars(
            select(VideoWorkEditingRunRecord).where(
                VideoWorkEditingRunRecord.batch_id == batch.id
            )
        )
    }
    base = f"/api/v1/video-studio/workspaces/{batch.workspace_id}/editing-tasks/"
    views: list[EditingItemView] = []
    position = 0
    for item in items:
        run = runs.get(item.id)
        view = EditingItemView(item_id=item.id, position=item.position)
        if run is None:
            view.waiting_for_source = not source_ready(item)
            views.append(view)
            continue
        view.phase, view.template_id = run.phase, run.template_id
        view.error, view.can_retry = run.error, run.phase == "failed"
        view.render_task_id = run.render_task_id
        if run.phase == "queued":
            position += 1
            view.queue_position = position
            view.estimate_minutes = (_global_ahead(session, run) + 1) * MINUTES_PER_ITEM
        elif run.phase in ACTIVE_PHASES:
            view.estimate_minutes = MINUTES_PER_ITEM
        task_id = run.render_task_id or run.transcript_task_id
        task = session.get(EditingTaskRecord, task_id) if task_id else None
        if task is not None:
            view.project_id = task.project_id
        if run.phase == "done" and task is not None:
            for artifact in session.scalars(
                select(EditingArtifactRecord).where(
                    EditingArtifactRecord.task_id == task.id,
                    EditingArtifactRecord.role.in_(("final", "poster")),
                )
            ):
                url = f"{base}{task.id}/artifacts/{artifact.id}"
                if artifact.role == "final":
                    view.final_url = url
                    view.duration_ms = artifact.duration_ms
                else:
                    view.poster_url = url
        views.append(view)
    return EditingBatchResponse(batch=batch_response(batch, items), editing=views)


# --------------------------------------------------------------------------- credits


def check_batch_credits(
    session: Session, settings: Settings, workspace_id: str, count: int
) -> None:
    """The whole batch is accepted or refused: N x (planning + render)."""
    prices = [
        video_credits.price_for(settings, action)
        for action in ("editing_planning", "editing_render")
    ]
    price = sum(value for value in prices if value)
    if not count or not price or not credit_enforcement_enabled(workspace_id):
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
            f"{count} 条剪辑需要 {required} 积分，当前可用 {available} 积分，"
            "请充值或减少条数后再生成。",
            {"required_credits": required, "available_credits": available},
        )


def _require_own_talking_items(
    session: Session,
    workspace: WorkspaceContext,
    batch_id: str,
    items: list[VideoWorkItemRecord],
) -> None:
    """A talking result must be edited as its own work item, never a copy.

    Its title, body and script live on the talking batch's item; editing it in
    a separate direct-editing batch would lose them in finishing and works.
    """
    generations = [
        str((item.source_video_ref or {}).get("id"))
        for item in items
        if (item.source_video_ref or {}).get("kind") in {"library", "talking"}
    ]
    if not generations:
        return
    owner = session.scalar(
        select(VideoWorkItemRecord).where(
            VideoWorkItemRecord.workspace_id == workspace.workspace_id,
            VideoWorkItemRecord.owner_user_id == workspace.principal.user_id,
            VideoWorkItemRecord.batch_id != batch_id,
            VideoWorkItemRecord.generation_task_id.in_(generations),
        )
    )
    if owner is not None:
        raise ApiError(
            409,
            "VIDEO_WORK_SOURCE_HAS_ITEM",
            "这条口播属于一个口播批次，请从那一批进入剪辑，标题和正文才不会丢。",
            {"batch_id": owner.batch_id, "item_id": owner.id},
        )


# --------------------------------------------------------------------------- routes


@router.post("/work-batches/{batch_id}/editing", response_model=EditingBatchResponse)
def submit_editing(
    batch_id: str,
    body: EditingBatchSubmit,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> EditingBatchResponse:
    """The user confirmed: freeze each item's choices and queue the batch."""
    require_workspace_write(workspace)
    settings: Settings = request.app.state.settings
    batch = _own_batch(session, workspace, batch_id)
    items = batch_items(session, batch.id)
    wanted = set(body.item_ids) if body.item_ids is not None else None
    if wanted is not None and not wanted <= {item.id for item in items}:
        raise ApiError(404, "VIDEO_WORK_ITEM_NOT_FOUND", "批次里没有这条作品。")
    unknown = set(body.items) - {item.id for item in items}
    if unknown:
        raise ApiError(404, "VIDEO_WORK_ITEM_NOT_FOUND", "批次里没有这条作品。")
    existing = {
        run.item_id: run
        for run in session.scalars(
            select(VideoWorkEditingRunRecord).where(
                VideoWorkEditingRunRecord.batch_id == batch.id
            )
        )
    }
    chosen: list[VideoWorkItemRecord] = []
    skipped = 0
    for item in items:
        if wanted is not None and item.id not in wanted:
            continue
        if item.id in existing:
            continue  # Already submitted (a repeat click or a second tab).
        if not source_ready(item):
            skipped += 1
            continue
        chosen.append(item)
    if batch.source == "editing_upload":
        _require_own_talking_items(session, workspace, batch.id, chosen)
    templates = {
        item.id: (body.items.get(item.id) or EditingItemChoice()).template_id
        or body.template_id
        for item in chosen
    }
    for template_id in set(templates.values()):
        require_active_planning_template(template_id, settings)
    check_batch_credits(session, settings, workspace.workspace_id, len(chosen))
    for item in chosen:
        choice = body.items.get(item.id) or EditingItemChoice()
        session.add(
            VideoWorkEditingRunRecord(
                item_id=item.id,
                batch_id=batch.id,
                workspace_id=workspace.workspace_id,
                owner_user_id=workspace.principal.user_id,
                request_id=str(body.request_id),
                attempt=1,
                template_id=templates[item.id],
                options={
                    "music": body.music,
                    "material_ids": sorted(str(value) for value in choice.material_ids),
                    "supplement": choice.supplement.model_dump(mode="json")
                    if choice.supplement
                    else None,
                },
                phase="queued",
            )
        )
    session.commit()
    for item in chosen:
        _write(session, item, stage="editing", status="queued", error=None)
    dispatch(session, settings, workspace, batch.id)
    view = editing_view(session, batch)
    if skipped:
        view.notice = f"还有 {skipped} 条口播没生成完，生成后可以再剪。"
    return view


@router.get("/work-batches/{batch_id}/editing", response_model=EditingBatchResponse)
def editing_status(
    batch_id: str,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> EditingBatchResponse:
    """Poll/restore: advances the batch, never starts anything unconfirmed."""
    batch = _own_batch(session, workspace, batch_id)
    if workspace.role.value != "viewer":
        dispatch(session, request.app.state.settings, workspace, batch.id)
    return editing_view(session, batch)


@router.post("/work-items/{item_id}/editing-retry", response_model=EditingBatchResponse)
def retry_editing(
    item_id: str,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> EditingBatchResponse:
    """Retry one failed item; the others are not touched.

    A failed render or a planning whose answer was saved is retried for free
    on the same task. Anything earlier starts a new attempt from that step,
    keeping finished earlier steps (a finished recognition is reused).
    """
    require_workspace_write(workspace)
    settings: Settings = request.app.state.settings
    item = _own_item(session, workspace, item_id)
    run = session.get(VideoWorkEditingRunRecord, item.id)
    if run is None or run.phase != "failed":
        return editing_view(session, _own_batch(session, workspace, item.batch_id))
    from .video_editing_planning_routes import retry_task as retry_planning
    from .video_editing_task_routes import retry_task as retry_render

    render = (
        session.get(EditingTaskRecord, run.render_task_id)
        if run.render_task_id
        else None
    )
    generated = (
        session.get(EditingPlanningTaskRecord, run.generate_task_id)
        if run.generate_task_id
        else None
    )
    if render is not None and render.status in {"failed", "cancelled"}:
        retry_render(UUID(render.id), request, workspace, session)
        run.phase = "rendering"
    elif (
        generated is not None
        and generated.status in {"failed", "cancelled"}
        and planning_response(generated, settings).get("call_state") == "response_saved"
        and run.error_code != "EDITING_PLAN_EMPTY_RESPONSE"
    ):
        retry_planning(UUID(generated.id), request, workspace, session)
        run.phase = "planning"
    else:
        transcript = (
            session.get(EditingTaskRecord, run.transcript_task_id)
            if run.transcript_task_id
            else None
        )
        keep = transcript is not None and transcript.status == "completed"
        check_batch_credits(session, settings, workspace.workspace_id, 1)
        run.attempt += 1
        run.prepare_task_id = run.generate_task_id = run.render_task_id = None
        run.phase = "transcribing" if keep else "queued"
        if not keep:
            run.transcript_task_id = None
    run.error = run.error_code = None
    session.commit()
    _write(
        session,
        item,
        stage="editing",
        status="queued" if run.phase == "queued" else "running",
        error=None,
    )
    dispatch(session, settings, workspace, item.batch_id)
    return editing_view(session, _own_batch(session, workspace, item.batch_id))


@router.get("/editing-sources", response_model=list[EditingSourceView])
def list_sources(
    workspace: VideoWorkspace,
    session: SessionDependency,
    limit: int = 50,
) -> list[EditingSourceView]:
    """The user's uploaded videos (视频库 · 已上传), newest first."""
    rows = session.scalars(
        select(EditingSourceRecord)
        .where(
            EditingSourceRecord.workspace_id == workspace.workspace_id,
            EditingSourceRecord.owner_user_id == workspace.principal.user_id,
            EditingSourceRecord.kind == "upload_asset",
        )
        .order_by(EditingSourceRecord.created_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    base = f"/api/v1/video-studio/workspaces/{workspace.workspace_id}/editing-sources/"
    views = []
    for row in rows:
        details = row.details or {}
        probe = details.get("probe") or details
        views.append(
            EditingSourceView(
                id=row.id,
                project_id=row.project_id,
                created_at=row.created_at,
                video_url=base + row.id + "/video",
                duration_ms=probe.get("duration_ms"),
                width=probe.get("width"),
                height=probe.get("height"),
                file_name=details.get("file_name") or details.get("filename"),
            )
        )
    return views


# --------------------------------------------------------------------------- sweep


def sweep_once(factory: sessionmaker[Session], settings: Settings) -> int:
    """Restart safety net: keep every confirmed batch moving.

    Runs at API start-up and every few seconds after, so a queued or running
    item continues after an API restart or with the page closed. Each step
    looks up its deterministic request id before creating anything.
    """
    with factory() as session:
        rows = session.execute(
            select(
                VideoWorkEditingRunRecord.batch_id,
                VideoWorkEditingRunRecord.workspace_id,
                VideoWorkEditingRunRecord.owner_user_id,
            )
            .where(VideoWorkEditingRunRecord.phase.in_(("queued", *ACTIVE_PHASES)))
            .distinct()
            .limit(50)
        ).all()
    moved = 0
    for batch_id, workspace_id, owner in rows:
        try:
            with factory() as session:
                workspace = _workspace_for(session, workspace_id, owner)
                if workspace is None:
                    continue
                dispatch(session, settings, workspace, batch_id)
                moved += 1
        except Exception:
            logger.exception("editing sweep deferred batch %s", batch_id)
    return moved


class EditingSweeper:
    """Runs ``sweep_once`` inside the API process, starting right at start-up."""

    def __init__(self, factory: sessionmaker[Session], settings: Settings) -> None:
        self.factory, self.settings = factory, settings
        self.stopped = Event()
        self.thread: Thread | None = None

    def run(self) -> None:
        while not self.stopped.is_set():
            try:
                sweep_once(self.factory, self.settings)
            except Exception:
                logger.warning("editing sweep deferred after an error", exc_info=True)
            self.stopped.wait(self.settings.video_recovery_interval_seconds)

    def start(self) -> None:
        self.thread = Thread(target=self.run, daemon=True, name="video-editing-sweep")
        self.thread.start()

    def stop(self) -> None:
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)
