"""User-owned, explicitly submitted Douyin search pages."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import Field, StringConstraints
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from .auth import SessionDependency, require_workspace_write
from .errors import ApiError
from .video_assistance import AssistanceResponse, process, provider, response
from .video_assistance_models import VideoAssistanceRecord
from .video_assistance_provider import benchmark_search_configured
from .video_benchmark import BENCHMARK_KIND, page_identity
from .video_studio_models import VideoProjectRecord
from .video_studio_routes import VideoWorkspace, scope
from .video_studio_schemas import StrictVideoModel

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}", tags=["video-assistance"]
)


class BenchmarkSearchRequest(StrictVideoModel):
    request_id: UUID
    project_id: UUID
    expected_revision: int = Field(ge=1)
    keyword: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
    ]
    sort: Literal["relevance", "newest", "most_liked"] = "relevance"
    publish_time: Literal["unlimited", "one_day", "one_week", "half_year"] = "unlimited"


class BenchmarkSearchConfig(StrictVideoModel):
    enabled: bool


def owned_searches(workspace: VideoWorkspace) -> Select[VideoAssistanceRecord]:
    return select(VideoAssistanceRecord).where(
        VideoAssistanceRecord.workspace_id == workspace.workspace_id,
        VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
    )


def replay(row: VideoAssistanceRecord, fingerprint: str) -> AssistanceResponse:
    if row.kind != BENCHMARK_KIND or row.request_hash != fingerprint:
        raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求标识已用于其他内容。")
    return response(row)


def require_search(request: Request) -> None:
    if not benchmark_search_configured(request.app.state.settings):
        raise ApiError(503, "VIDEO_ASSISTANCE_DISABLED", "对标搜索尚未配置。")


def save_page(
    session: SessionDependency,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    project_id: str,
    request_id: str,
    fingerprint: str,
    inputs: dict[str, Any],
) -> AssistanceResponse:
    task_id = str(uuid4())
    row = VideoAssistanceRecord(
        id=task_id,
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=project_id,
        request_id=request_id,
        request_hash=fingerprint,
        kind=BENCHMARK_KIND,
        inputs=inputs,
        result=page_identity(task_id, inputs),
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            owned_searches(workspace).where(
                VideoAssistanceRecord.request_id == request_id
            )
        )
        if existing is None:
            raise
        return replay(existing, fingerprint)
    background.add_task(
        process, request.app.state.session_factory, row.id, provider(request)
    )
    return response(row)


@router.get("/benchmark-config", response_model=BenchmarkSearchConfig)
def search_config(request: Request, workspace: VideoWorkspace) -> BenchmarkSearchConfig:
    return BenchmarkSearchConfig(
        enabled=benchmark_search_configured(request.app.state.settings)
    )


@router.post("/benchmark-searches", response_model=AssistanceResponse)
def submit_search(
    body: BenchmarkSearchRequest,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> AssistanceResponse:
    require_workspace_write(workspace)
    request_id = str(body.request_id)
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    existing = session.scalar(
        owned_searches(workspace).where(VideoAssistanceRecord.request_id == request_id)
    )
    if existing:
        return replay(existing, fingerprint)
    require_search(request)
    project = session.scalar(
        select(VideoProjectRecord).where(
            VideoProjectRecord.id == str(body.project_id), *scope(workspace)
        )
    )
    if project is None:
        raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
    if project.revision != body.expected_revision:
        raise ApiError(409, "VIDEO_REVISION_CONFLICT", "项目已变化，请重新载入后确认。")
    return save_page(
        session,
        request,
        background,
        workspace,
        project.id,
        request_id,
        fingerprint,
        {
            "revision": project.revision,
            "search_params": {
                "keyword": body.keyword,
                "sort": body.sort,
                "publish_time": body.publish_time,
                "page_token": "",
                "limit": 10,
            },
            "page": 1,
            "root_task_id": None,
            "previous_task_id": None,
            "seen_ids": [],
        },
    )


@router.post("/benchmark-searches/{task_id}/next", response_model=AssistanceResponse)
def next_page(
    task_id: UUID,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> AssistanceResponse:
    require_workspace_write(workspace)
    parent = session.scalar(
        owned_searches(workspace).where(
            VideoAssistanceRecord.id == str(task_id),
            VideoAssistanceRecord.kind == BENCHMARK_KIND,
        )
    )
    if parent is None:
        raise ApiError(404, "VIDEO_BENCHMARK_NOT_FOUND", "未找到对标搜索。")
    marker = f"tengli-video-benchmark-page:{parent.id}"
    request_id = str(uuid5(NAMESPACE_URL, marker))
    fingerprint = hashlib.sha256(marker.encode()).hexdigest()
    existing = session.scalar(
        owned_searches(workspace).where(VideoAssistanceRecord.request_id == request_id)
    )
    if existing:
        return replay(existing, fingerprint)
    require_search(request)
    token = parent.receipt.get("next_page_token")
    if parent.status != "completed" or not token:
        raise ApiError(
            409, "VIDEO_BENCHMARK_NO_NEXT_PAGE", "当前任务没有可用的下一页。"
        )
    if datetime.now(UTC) >= datetime.fromisoformat(
        parent.result["next_page_expires_at"]
    ):
        raise ApiError(409, "VIDEO_BENCHMARK_PAGE_EXPIRED", "翻页已过期，请重新搜索。")
    return save_page(
        session,
        request,
        background,
        workspace,
        parent.project_id,
        request_id,
        fingerprint,
        {
            **parent.inputs,
            "search_params": {**parent.inputs["search_params"], "page_token": token},
            "page": parent.result["page"] + 1,
            "root_task_id": parent.result["root_task_id"],
            "previous_task_id": parent.id,
            "seen_ids": parent.receipt["seen_ids"],
        },
    )
