"""User-owned benchmark pages: explicit keyword searches or pasted links."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import Field, StringConstraints
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from . import video_benchmark_platforms as platforms
from . import video_credit_billing as video_credits
from .auth import SessionDependency, require_workspace_write
from .errors import ApiError
from .video_assistance import AssistanceResponse, process, provider, response
from .video_assistance_models import VideoAssistanceRecord
from .video_assistance_provider import benchmark_search_configured, video_source_url
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
    platform: Literal["douyin", "xiaohongshu", "bilibili"] = "douyin"
    # Accepted for older clients; every search is ordered by likes.
    sort: Literal["relevance", "newest", "most_liked"] = "most_liked"
    publish_time: Literal["unlimited", "one_day", "one_week", "half_year"] = "unlimited"


class BenchmarkLinksRequest(StrictVideoModel):
    request_id: UUID
    project_id: UUID
    expected_revision: int = Field(ge=1)
    text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=8, max_length=4000)
    ]


class BenchmarkSearchConfig(StrictVideoModel):
    enabled: bool
    can_extract: bool
    can_save_reference: bool


class BenchmarkExtractionPick(StrictVideoModel):
    search_task_id: UUID
    platform_id: str = Field(pattern=r"^[0-9A-Za-z]{6,32}$")


class BenchmarkExtractionRequest(StrictVideoModel):
    project_id: UUID
    expected_revision: int = Field(ge=1)
    items: list[BenchmarkExtractionPick] = Field(min_length=1, max_length=3)


# Select[Any]: the Select type parameters differ between SQLAlchemy 2.0 and 2.1.
def owned_searches(workspace: VideoWorkspace) -> Select[Any]:
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
        video_credits.hold(
            session,
            request.app.state.settings,
            workspace.workspace_id,
            "benchmark_search",
            "video_assistance",
            row.id,
        )
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
    background.add_task(
        video_credits.settle_after,
        request.app.state.session_factory,
        "video_assistance",
        row.id,
    )
    return response(row)


@router.get("/benchmark-config", response_model=BenchmarkSearchConfig)
def search_config(request: Request, workspace: VideoWorkspace) -> BenchmarkSearchConfig:
    settings = request.app.state.settings
    return BenchmarkSearchConfig(
        enabled=benchmark_search_configured(settings),
        can_extract=settings.video_extract_enabled
        and bool(settings.video_extract_api_key.get_secret_value().strip()),
        can_save_reference=settings.video_writing_workflow_enabled,
    )


@router.post("/benchmark-extractions", response_model=list[AssistanceResponse])
def extract_candidates(
    body: BenchmarkExtractionRequest,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> list[AssistanceResponse]:
    require_workspace_write(workspace)
    project = session.scalar(
        select(VideoProjectRecord).where(
            VideoProjectRecord.id == str(body.project_id), *scope(workspace)
        )
    )
    if project is None:
        raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
    if len({item.platform_id for item in body.items}) != len(body.items):
        raise ApiError(422, "VIDEO_BENCHMARK_DUPLICATE", "请只勾选同一作品一次。")

    pages = {
        row.id: row
        for row in session.scalars(
            owned_searches(workspace).where(
                VideoAssistanceRecord.id.in_(
                    [str(pick.search_task_id) for pick in body.items]
                ),
                VideoAssistanceRecord.project_id == project.id,
                VideoAssistanceRecord.kind == BENCHMARK_KIND,
                VideoAssistanceRecord.status == "completed",
            )
        )
    }
    entries = {}
    details: dict[str, dict[str, Any]] = {}
    for pick in body.items:
        page = pages.get(str(pick.search_task_id))
        source = next(
            (
                row
                for row in (page.result.get("items", []) if page else [])
                if row["platform_id"] == pick.platform_id
            ),
            None,
        )
        if page is None or source is None:
            raise ApiError(404, "VIDEO_BENCHMARK_NOT_FOUND", "未找到本项目的对标作品。")
        platform = source.get("platform", "douyin")
        marker = f"tengli-benchmark-extraction:{project.id}:{pick.platform_id}"
        if platform != "douyin":
            marker = (
                f"tengli-benchmark-extraction:{project.id}:{platform}:"
                + pick.platform_id
            )
        url = (
            video_source_url(source["source_url"])
            if platform == "douyin"
            else source["source_url"]
        )
        entries[str(uuid5(NAMESPACE_URL, marker))] = (
            hashlib.sha256(marker.encode()).hexdigest(),
            {
                "search_task_id": page.id,
                "platform": platform,
                "platform_id": pick.platform_id,
                "source_url": url,
                "keyword": page.result["keyword"],
                "captured_at": page.result["captured_at"],
            },
        )
        details[str(uuid5(NAMESPACE_URL, marker))] = {
            "item": {
                key: source.get(key)
                for key in (
                    "title",
                    "description",
                    "author_name",
                    "author_follower_count",
                    "duration_seconds",
                    "posted_at",
                    "like_count",
                    "comment_count",
                    "collect_count",
                    "share_count",
                    "view_count",
                )
            },
            "media_url": (page.receipt.get("media_urls") or {}).get(pick.platform_id),
        }
    existing_query = owned_searches(workspace).where(
        VideoAssistanceRecord.request_id.in_(entries)
    )
    settings = request.app.state.settings
    for attempt in range(2):
        rows = {row.request_id: row for row in session.scalars(existing_query)}
        if any(
            row.kind != "extract" or row.request_hash != entries[rid][0]
            for rid, row in rows.items()
        ):
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "此请求已用于其他内容。")
        if len(rows) == len(entries):
            return [response(rows[rid]) for rid in entries]
        if project.revision != body.expected_revision:
            raise ApiError(
                409, "VIDEO_REVISION_CONFLICT", "项目已变化，请重新载入后确认。"
            )
        if not (
            settings.video_extract_enabled
            and settings.video_extract_api_key.get_secret_value().strip()
        ):
            raise ApiError(503, "VIDEO_ASSISTANCE_DISABLED", "语音提取服务尚未配置。")
        new = []
        for rid, (fingerprint, source_info) in entries.items():
            if rid in rows:
                continue
            row = VideoAssistanceRecord(
                id=str(uuid4()),
                workspace_id=workspace.workspace_id,
                owner_user_id=workspace.principal.user_id,
                project_id=project.id,
                request_id=rid,
                request_hash=fingerprint,
                kind="extract",
                inputs={
                    "revision": project.revision,
                    "platform": source_info["platform"],
                    "source_url": source_info["source_url"],
                    "title": details[rid]["item"].get("title") or "",
                    "media_url": details[rid]["media_url"],
                    "benchmark_item": details[rid]["item"],
                    "benchmark_source": source_info,
                },
            )
            rows[rid] = row
            new.append(row)
        session.add_all(new)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            if attempt == 0:
                continue
            break
        service = provider(request)
        for row in new:
            background.add_task(
                process, request.app.state.session_factory, row.id, service
            )
        return [response(rows[rid]) for rid in entries]
    raise ApiError(409, "VIDEO_REQUEST_REUSED", "批量提取任务发生冲突，请刷新后确认。")


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
            "platform": body.platform,
            "mode": "search",
            "search_params": {
                "keyword": body.keyword,
                "sort": "most_liked",
                "publish_time": body.publish_time
                if body.platform == "douyin"
                else "unlimited",
                "page_token": "",
                "limit": 20,
            },
            "page": 1,
            "root_task_id": None,
            "previous_task_id": None,
            "seen_ids": [],
        },
    )


@router.post("/benchmark-links", response_model=AssistanceResponse)
def submit_links(
    body: BenchmarkLinksRequest,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> AssistanceResponse:
    """Pasted share text with up to three post links; free detail lookups."""
    require_workspace_write(workspace)
    request_id = str(body.request_id)
    fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    existing = session.scalar(
        owned_searches(workspace).where(VideoAssistanceRecord.request_id == request_id)
    )
    if existing:
        return replay(existing, fingerprint)
    require_search(request)
    found = platforms.links_in(body.text)
    if not found:
        raise ApiError(
            422,
            "VIDEO_SOURCE_URL_INVALID",
            "没有找到链接，请粘贴抖音、小红书或 B站的分享链接。",
        )
    if len(found) > platforms.MAX_LINKS:
        raise ApiError(422, "VIDEO_BENCHMARK_TOO_MANY_LINKS", "一次最多粘贴 3 条链接。")
    links: list[dict[str, str]] = []
    for link in found:
        platform, post, url = platforms.resolve_link(link)
        if all(row["id"] != post for row in links):
            links.append({"platform": platform, "id": post, "url": url})
    project = session.scalar(
        select(VideoProjectRecord).where(
            VideoProjectRecord.id == str(body.project_id), *scope(workspace)
        )
    )
    if project is None:
        raise ApiError(404, "VIDEO_PROJECT_NOT_FOUND", "未找到项目。")
    if project.revision != body.expected_revision:
        raise ApiError(409, "VIDEO_REVISION_CONFLICT", "项目已变化，请重新载入后确认。")
    task_id = str(uuid4())
    inputs = {
        "revision": project.revision,
        "platform": links[0]["platform"]
        if len({r["platform"] for r in links}) == 1
        else "mixed",
        "mode": "links",
        "links": links,
        "search_params": {
            "keyword": "粘贴的链接",
            "sort": "most_liked",
            "publish_time": "unlimited",
            "page_token": "",
        },
        "page": 1,
        "root_task_id": None,
        "previous_task_id": None,
        "seen_ids": [],
    }
    row = VideoAssistanceRecord(
        id=task_id,
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=project.id,
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
