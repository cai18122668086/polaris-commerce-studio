"""Owned asynchronous source extraction and script planning, never auto-applied."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .auth import SessionDependency, require_workspace_write
from .errors import ApiError
from .models import utc_now
from .video_assistance_models import VideoAssistanceRecord
from .video_assistance_provider import (
    VideoAssistanceProvider,
    transcript_result,
    video_source_url,
)
from .video_benchmark import BENCHMARK_KIND, benchmark_page
from .video_stage_timing import transition
from .video_studio_models import VideoProjectRecord
from .video_studio_routes import VideoWorkspace, scope
from .video_studio_schemas import StrictVideoModel

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}", tags=["video-assistance"]
)


class AssistanceRequest(StrictVideoModel):
    request_id: UUID
    project_id: UUID
    expected_revision: int = Field(ge=1)
    kind: Literal["create", "rewrite", "extract"]
    brief: str = Field(default="", max_length=6000)
    style: Literal["产品介绍", "好物种草", "知识分享", "品牌故事"] = "产品介绍"
    reference_id: UUID | None = None


class BenchmarkExtractionSource(StrictVideoModel):
    search_task_id: UUID
    platform_id: str
    source_url: str
    keyword: str
    captured_at: datetime


class AssistanceResponse(StrictVideoModel):
    id: UUID
    request_id: UUID
    project_id: UUID
    kind: str
    status: str
    stage: str
    error_code: str | None
    source_revision: int
    result: dict
    can_resume: bool
    benchmark_source: BenchmarkExtractionSource | None = None
    stage_history: list[dict] = Field(default_factory=list)
    receipt: dict = Field(default_factory=dict)


def provider(request: Request) -> VideoAssistanceProvider:
    return getattr(
        request.app.state, "video_assistance_provider", None
    ) or VideoAssistanceProvider(request.app.state.settings)


def response(row: VideoAssistanceRecord) -> AssistanceResponse:
    return AssistanceResponse(
        id=UUID(row.id),
        request_id=UUID(row.request_id),
        project_id=UUID(row.project_id),
        kind=row.kind,
        status=row.status,
        stage=row.stage,
        error_code=row.error_code,
        source_revision=row.inputs["revision"],
        result=row.result,
        can_resume=row.status in {"queued", "awaiting_resume"},
        benchmark_source=row.inputs.get("benchmark_source"),
        stage_history=row.receipt.get("stage_history", []),
        receipt={},  # Supplier receipts remain server-side.
    )


def checkpoint(
    session: Session, row: VideoAssistanceRecord, stage: str, **values: Any
) -> None:
    history = transition(row.receipt.get("stage_history"), stage)
    if stage == "completed":
        history = transition(history, stage, finish=True, outcome="completed")
    row.stage = stage
    for key, value in values.items():
        setattr(row, key, value)
    row.receipt = {**row.receipt, "stage_history": history}
    session.commit()


def process(
    factory: sessionmaker[Session], task_id: str, service: VideoAssistanceProvider
) -> None:
    with factory() as session:
        changed = session.execute(
            update(VideoAssistanceRecord)
            .where(
                VideoAssistanceRecord.id == task_id,
                VideoAssistanceRecord.status == "queued",
            )
            .values(status="running", error_code=None)
        )
        session.commit()
        if cast(CursorResult[Any], changed).rowcount != 1:
            return
        row = session.get(VideoAssistanceRecord, task_id)
        if row is None:
            return
        session.commit()
        checkpoint(session, row, "extracting" if row.provider_task_id else row.stage)
        try:
            if row.kind == BENCHMARK_KIND:
                checkpoint(session, row, "submitting")
                captured_at = utc_now()
                data = service.benchmark_search(row.inputs["search_params"])
                result, receipt = benchmark_page(data, row.id, row.inputs, captured_at)
                row.status = "completed"
                checkpoint(session, row, "completed", result=result, receipt=receipt)
                return
            elif row.kind != "extract":
                checkpoint(session, row, "submitting")
                result, receipt = service.plan(row.kind, row.inputs)
                checkpoint(session, row, "received", result=result, receipt=receipt)
                if result.get("validation_error"):
                    raise ApiError(
                        502,
                        "VIDEO_SCRIPT_INVALID",
                        "文案未通过格式或事实检查，请核对产品事实。",
                    )
            else:
                if not row.provider_task_id:
                    checkpoint(session, row, "submitting")
                    data = service.extract(row.inputs)
                    # Store the provider ID before any polling. A lost submit
                    # response must never cause another charged extraction.
                    if not data.get("job_id"):
                        if "results" not in data:
                            raise ApiError(
                                502,
                                "VIDEO_ASSISTANCE_OUTCOME_UNKNOWN",
                                "提取提交结果未确认。",
                            )
                        checkpoint(
                            session,
                            row,
                            "received",
                            result=transcript_result(data, row.inputs["source_url"]),
                            receipt={"billing": data.get("billing")},
                        )
                        row.status = "completed"
                        checkpoint(session, row, "completed")
                        return
                    checkpoint(
                        session,
                        row,
                        "extracting",
                        provider_task_id=data["job_id"],
                        receipt={
                            "billing": data.get("billing"),
                            "provider_id": data.get("id"),
                        },
                    )
                for _ in range(120):
                    row.updated_at = utc_now()
                    session.commit()
                    try:
                        data = service.extract_status(row.provider_task_id or "")
                    except ApiError:
                        time.sleep(3)
                        continue
                    status = data.get("status")
                    if status == "succeeded":
                        checkpoint(
                            session,
                            row,
                            "received",
                            result=transcript_result(data, row.inputs["source_url"]),
                            receipt={
                                **row.receipt,
                                "billing": data.get("billing")
                                or row.receipt.get("billing"),
                            },
                        )
                        break
                    if status == "failed":
                        raise ApiError(
                            502,
                            "VIDEO_EXTRACT_FAILED",
                            "视频语音提取失败，请核对链接或粘贴原文。",
                        )
                    # submit_unknown with a known ID is poll-only, never POST.
                    time.sleep(3)
                else:
                    row.status = "awaiting_resume"
                    row.receipt = {
                        **row.receipt,
                        "stage_history": transition(
                            row.receipt.get("stage_history"),
                            row.stage,
                            finish=True,
                            outcome="awaiting_resume",
                        ),
                    }
                    session.commit()
                    return
            row.status = "completed"
            checkpoint(session, row, "completed")
        except Exception as error:
            session.rollback()
            row = session.get(VideoAssistanceRecord, task_id)
            if row is None:
                return
            code = (
                error.code if isinstance(error, ApiError) else "VIDEO_ASSISTANCE_FAILED"
            )
            row.error_code = code
            row.status = (
                "unknown"
                if code == "VIDEO_ASSISTANCE_OUTCOME_UNKNOWN"
                or (
                    row.stage == "submitting"
                    and code
                    not in {
                        "VIDEO_ASSISTANCE_REJECTED",
                        "VIDEO_ASSISTANCE_DISABLED",
                        "VIDEO_TRANSCRIPT_EMPTY",
                        "VIDEO_TRANSCRIPT_TOO_LONG",
                    }
                )
                else "failed"
            )
            row.receipt = {
                **row.receipt,
                "stage_history": transition(
                    row.receipt.get("stage_history"),
                    row.stage,
                    finish=True,
                    outcome=row.status,
                ),
            }
            session.commit()


@router.post("/assistance-tasks", response_model=AssistanceResponse)
def submit(
    body: AssistanceRequest,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> AssistanceResponse:
    require_workspace_write(workspace)
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    existing = session.scalar(
        select(VideoAssistanceRecord).where(
            VideoAssistanceRecord.workspace_id == workspace.workspace_id,
            VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
            VideoAssistanceRecord.request_id == str(body.request_id),
        )
    )
    if existing:
        if existing.request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求标识已用于其他内容。")
        return response(existing)
    settings = request.app.state.settings
    if not (
        settings.video_extract_enabled
        if body.kind == "extract"
        else settings.video_script_planning_enabled
    ):
        raise ApiError(503, "VIDEO_ASSISTANCE_DISABLED", "文案服务尚未配置。")
    project = session.scalar(
        select(VideoProjectRecord).where(
            VideoProjectRecord.id == str(body.project_id), *scope(workspace)
        )
    )
    if not project:
        raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
    if project.revision != body.expected_revision:
        raise ApiError(409, "VIDEO_REVISION_CONFLICT", "项目已变化，请重新载入后确认。")
    refs = project.content.get("references", [])
    ref = (
        next((r for r in refs if r["id"] == str(body.reference_id)), None)
        if body.reference_id
        else (refs[0] if refs else None)
    )
    inputs = {
        "revision": project.revision,
        "product_facts": project.content.get("product_facts", ""),
        "brief": body.brief,
        "style": body.style,
    }
    if body.kind == "create" and not body.brief.strip():
        raise ApiError(422, "VIDEO_BRIEF_REQUIRED", "请填写创作需求与已确认产品信息。")
    if body.kind in {"rewrite", "extract"}:
        if not ref:
            raise ApiError(
                422, "VIDEO_REFERENCE_REQUIRED", "请先保存参考文案或视频链接。"
            )
        inputs.update(
            reference_id=ref["id"],
            source_url=ref.get("url", ""),
            reference_text=ref.get("original_text", ""),
        )
        if body.kind == "rewrite" and not inputs["reference_text"].strip():
            raise ApiError(422, "VIDEO_REFERENCE_REQUIRED", "请先提取或粘贴原文。")
        if body.kind == "extract":
            inputs["original_source_url"] = inputs["source_url"]
            inputs["source_url"] = video_source_url(inputs["source_url"])
    row = VideoAssistanceRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=project.id,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        kind=body.kind,
        inputs=inputs,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(VideoAssistanceRecord).where(
                VideoAssistanceRecord.workspace_id == workspace.workspace_id,
                VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
                VideoAssistanceRecord.request_id == str(body.request_id),
            )
        )
        if not existing or existing.request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求冲突。") from None
        return response(existing)
    background.add_task(
        process, request.app.state.session_factory, row.id, provider(request)
    )
    return response(row)


@router.get("/assistance-tasks", response_model=list[AssistanceResponse])
def tasks(
    project_id: UUID, workspace: VideoWorkspace, session: SessionDependency
) -> list[AssistanceResponse]:
    rows = session.scalars(
        select(VideoAssistanceRecord)
        .where(
            VideoAssistanceRecord.workspace_id == workspace.workspace_id,
            VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
            VideoAssistanceRecord.project_id == str(project_id),
        )
        .order_by(VideoAssistanceRecord.created_at.desc())
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
            and (datetime.now(UTC) - stamp).total_seconds() > 180
        ):
            row.status = (
                "awaiting_resume"
                if row.kind == "extract" and row.provider_task_id
                else "unknown"
            )
    session.commit()
    return [response(row) for row in rows]


@router.post("/assistance-tasks/{task_id}/resume", response_model=AssistanceResponse)
def resume(
    task_id: UUID,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> AssistanceResponse:
    require_workspace_write(workspace)
    row = session.scalar(
        select(VideoAssistanceRecord).where(
            VideoAssistanceRecord.id == str(task_id),
            VideoAssistanceRecord.workspace_id == workspace.workspace_id,
            VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
        )
    )
    if not row:
        raise ApiError(404, "VIDEO_ASSISTANCE_NOT_FOUND", "未找到文案任务。")
    if row.status not in {"queued", "awaiting_resume"}:
        raise ApiError(
            409, "VIDEO_ASSISTANCE_NOT_RESUMABLE", "请保留原任务核对，不要重复提交。"
        )
    changed = session.execute(
        update(VideoAssistanceRecord)
        .where(
            VideoAssistanceRecord.id == row.id,
            VideoAssistanceRecord.status == row.status,
        )
        .values(status="queued")
    )
    session.commit()
    session.refresh(row)
    if cast(CursorResult[Any], changed).rowcount == 1:
        background.add_task(
            process, request.app.state.session_factory, row.id, provider(request)
        )
    return response(row)
