"""Supplement-material panel API (contract C5, W4 v3).

Workspace-scoped helpers for the four optional sources of editing step ③:
my uploads (existing ``/editing-materials`` upload), free stock libraries,
AI images and MG motion graphics. Everything a user picks ends up as an
ordinary project material (``video_editing_materials``) whose ids the editing
line passes as ``material_ids``; MG is a frozen planning option.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import shutil
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import video_credit_billing as video_credits
from .auth import SessionDependency, require_workspace_write
from .config import Settings
from .errors import ApiError
from .models import utc_now
from .video_editing_material_routes import response as material_response
from .video_editing_material_routes import scope as material_scope
from .video_editing_materials import material_file
from .video_editing_stock_fetch import FetchError, cache_root, fetch_media, fetch_thumb
from .video_editing_stock_sources import LABELS, Candidate, search_sentence, states
from .video_editing_supplement_plan import ScriptAnalysis, analyze_script
from .video_editing_task_models import (
    EditingImageRequestRecord,
    EditingMaterialRecord,
    EditingPlanningTaskRecord,
)
from .video_editing_task_routes import enabled, own_project
from .video_studio_routes import VideoWorkspace
from .video_studio_schemas import StrictVideoModel

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}/editing-supplement",
    tags=["video-editing-supplement"],
)
MATERIAL_ROOT = (
    "/api/v1/video-studio/workspaces/{workspace_id}"
    "/projects/{project_id}/editing-materials"
)
material_router = APIRouter(prefix=MATERIAL_ROOT, tags=["video-editing-materials"])
MAX_STOCK_SENTENCES = 8
CHARS_PER_SECOND = 4.5
_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------- schemas


class ScriptBody(StrictVideoModel):
    script_text: str = Field(min_length=1, max_length=4000)


class StockSearchBody(ScriptBody):
    sentence_indexes: list[int] | None = Field(default=None, max_length=12)
    # 已被「我的素材」占用的句子：每句最多一个补充素材。
    exclude_sentences: list[int] = Field(default_factory=list, max_length=60)
    limit: int = Field(default=3, ge=1, le=3)


class StockImportBody(StrictVideoModel):
    project_id: UUID
    request_id: UUID
    token: str = Field(pattern=r"^[0-9a-f]{32}$")
    sentence_index: int = Field(ge=0, le=60)
    sentence: str = Field(min_length=1, max_length=300)
    work_item_ref: str | None = Field(default=None, max_length=64)


class AiEstimateBody(ScriptBody):
    max_images: int = Field(default=4, ge=1, le=6)
    # 已有我的素材 / 免费素材的句子不再配 AI 图（方案 4.1：只补没素材的段落）。
    exclude_sentences: list[int] = Field(default_factory=list, max_length=60)


class AiImageItem(StrictVideoModel):
    request_id: UUID
    sentence_index: int = Field(ge=0, le=60)
    sentence: str = Field(min_length=1, max_length=300)
    subject: str = Field(min_length=2, max_length=80)
    purpose: Literal["scene", "usage", "texture", "concept", "comparison"] = "scene"


class AiImagesBody(StrictVideoModel):
    project_id: UUID
    work_item_ref: str | None = Field(default=None, max_length=64)
    style: Literal["bright", "warm", "minimal"] = "bright"
    items: list[AiImageItem] = Field(min_length=1, max_length=6)


class AiRegenerateBody(StrictVideoModel):
    request_id: UUID
    subject: str | None = Field(default=None, min_length=2, max_length=80)


# ---------------------------------------------------------------- helpers


def _settings(request: Request) -> Settings:
    return enabled(request)


def _candidate_dir(settings: Settings) -> Path:
    return cache_root(settings) / "candidates"


def _token(candidate: Candidate) -> str:
    return hashlib.sha256(
        f"{candidate.key}|{candidate.download_url}".encode()
    ).hexdigest()[:32]


def _remember(settings: Settings, candidate: Candidate) -> str:
    token = _token(candidate)
    folder = _candidate_dir(settings)
    path = folder / f"{token}.json"
    if not path.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{token}.tmp"
        tmp.write_text(json.dumps(candidate.to_json(), ensure_ascii=False), "utf-8")
        tmp.replace(path)
    return token


def _recall(settings: Settings, token: str) -> Candidate:
    try:
        data = json.loads(
            (_candidate_dir(settings) / f"{token}.json").read_text("utf-8")
        )
        return Candidate.from_json(data)
    except (OSError, ValueError, TypeError):
        raise ApiError(
            404, "SUPPLEMENT_STOCK_EXPIRED", "这个素材候选已过期，请重新搜索。"
        ) from None


def _short_label(text: str) -> str:
    return re.sub(r"[，。！？!?；;、,.\s]+$", "", text.strip())[:16] or "配图"


def price(settings: Settings) -> int | None:
    from .video_credit_billing import price_for

    return price_for(settings, "editing_auto_image")


def pick_paintable(
    analysis: ScriptAnalysis, max_images: int, exclude: Sequence[int] = ()
) -> list[dict[str, Any]]:
    """Plan §4.1: drawable, uncovered sentences only, ≤2 per 30 s, not adjacent."""
    seconds = sum(len(row.text) for row in analysis.sentences) / CHARS_PER_SECOND
    cap = min(max_images, 6, max(1, math.ceil(seconds / 30)) * 2)
    chosen: list[dict[str, Any]] = []
    last = -2
    for row in analysis.sentences:
        if len(chosen) >= cap:
            break
        # Sentence 0 is the template opening title: materials never show there.
        if row.paintable and row.index > max(last + 1, 0) and row.index not in exclude:
            chosen.append(
                {
                    "sentence_index": row.index,
                    "sentence": row.text,
                    "subject": row.subject,
                    "purpose": row.purpose,
                }
            )
            last = row.index
    return chosen


def pick_stock_sentences(
    analysis: ScriptAnalysis, exclude: Sequence[int] = ()
) -> list[int]:
    preferred = {"scene": 0, "selling": 1, "data": 2, "compare": 2, "steps": 3}
    rows = [
        row
        for row in analysis.sentences
        if row.queries and row.index > 0 and row.index not in exclude
    ]
    rows.sort(key=lambda row: (preferred.get(row.type, 4), row.index))
    chosen: list[int] = []
    for row in rows:
        if len(chosen) >= MAX_STOCK_SENTENCES:
            break
        if all(abs(row.index - other) > 1 for other in chosen):
            chosen.append(row.index)
    return sorted(chosen)


# ---------------------------------------------------------------- sources


@router.get("/sources")
async def sources(request: Request, workspace: VideoWorkspace) -> dict[str, Any]:
    from .mg.catalog import COMPONENTS, MG_TEMPLATES, MG_UNSUPPORTED_REASON, STYLES
    from .video_editing_stock_sources import probe_fallbacks
    from .video_editing_supplement_images import available as ai_available

    settings = _settings(request)
    await asyncio.to_thread(probe_fallbacks, settings)
    stock = [
        {
            "provider": row.provider,
            "label": LABELS[row.provider],
            "available": row.available,
            "reason": row.reason,
        }
        for row in states(settings)
    ]
    stock_ok = any(row["available"] for row in stock)
    credits = price(settings)
    return {
        "sources": [
            {"key": "mine", "available": True, "reason": None, "price": "免费"},
            {
                "key": "stock",
                "available": stock_ok,
                "reason": None if stock_ok else "暂未开通",
                "price": "免费",
            },
            {
                "key": "ai_image",
                "available": ai_available(settings),
                "reason": None if ai_available(settings) else "暂未开通",
                "price": f"{credits} 积分/张" if credits else "灰度测试期间不扣积分",
                "credits_per_image": credits,
                "max_images": settings.video_supplement_ai_image_max_per_video,
            },
            {
                "key": "mg",
                "available": settings.video_supplement_mg_enabled,
                "reason": None if settings.video_supplement_mg_enabled else "暂未开通",
                "price": "免费",
            },
        ],
        "stock_providers": stock,
        "mg_templates": sorted(MG_TEMPLATES),
        "mg_unsupported_reason": MG_UNSUPPORTED_REASON,
        "mg_styles": [
            {"key": key, "label": value["label"]} for key, value in STYLES.items()
        ],
        "mg_components": [
            {"key": key, "label": value["label"], "use": value["use"]}
            for key, value in COMPONENTS.items()
        ],
    }


@router.post("/analyze")
async def analyze(
    request: Request, workspace: VideoWorkspace, body: ScriptBody
) -> dict[str, Any]:
    settings = _settings(request)
    result = await asyncio.to_thread(analyze_script, settings, body.script_text)
    return result.public()


# ---------------------------------------------------------------- stock


@router.post("/stock/search")
async def stock_search(
    request: Request, workspace: VideoWorkspace, body: StockSearchBody
) -> dict[str, Any]:
    settings = _settings(request)
    analysis = await asyncio.to_thread(analyze_script, settings, body.script_text)
    indexes = (
        [i for i in body.sentence_indexes if 0 <= i < len(analysis.sentences)]
        if body.sentence_indexes is not None
        else pick_stock_sentences(analysis, body.exclude_sentences)
    )

    def one(index: int) -> dict[str, Any]:
        row = analysis.sentences[index]
        found = search_sentence(
            settings,
            row.queries,
            limit=body.limit,
            want_video=settings.video_stock_include_video,
        )
        return {
            "index": index,
            "text": row.text,
            "queries": row.queries,
            "candidates": [
                {**candidate.public(), "token": _remember(settings, candidate)}
                for candidate in found
            ],
        }

    def run() -> list[dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(one, indexes))

    sentences = await asyncio.to_thread(run)
    available = [row.provider for row in states(settings) if row.available]
    return {
        "analysis_source": analysis.source,
        "providers": available,
        "sentences": sentences,
    }


@router.get("/stock/thumb/{token}")
async def stock_thumb(
    request: Request, workspace: VideoWorkspace, token: str
) -> Response:
    settings = _settings(request)
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise ApiError(404, "SUPPLEMENT_STOCK_EXPIRED", "素材缩略图不存在。")
    candidate = _recall(settings, token)
    try:
        data = await asyncio.to_thread(
            fetch_thumb, settings, candidate.provider, candidate.thumb_url
        )
    except FetchError:
        raise ApiError(502, "SUPPLEMENT_STOCK_THUMB", "缩略图暂时取不到。") from None
    return Response(
        data,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/stock/import", status_code=201)
async def stock_import(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    body: StockImportBody,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    settings = _settings(request)
    own_project(session, workspace, str(body.project_id))
    identity = (
        *material_scope(workspace, body.project_id),
        EditingMaterialRecord.request_id == str(body.request_id),
    )
    old = session.scalar(select(EditingMaterialRecord).where(*identity))
    if old is not None:
        if (old.provenance or {}).get("token") != body.token:
            raise ApiError(
                409, "EDITING_MATERIAL_REQUEST_REUSED", "素材请求编号已用于其他输入。"
            )
        return material_response(old)
    candidate = _recall(settings, body.token)
    try:
        path, mime, width, height = await asyncio.to_thread(
            fetch_media, settings, candidate
        )
    except FetchError as error:
        message = {
            "STOCK_TOO_LARGE": "这个素材文件太大，换一个试试。",
            "STOCK_HOST_NOT_ALLOWED": "素材来源地址不在允许范围内。",
        }.get(error.code, "素材下载失败，请换一个或稍后再试。")
        raise ApiError(502, "SUPPLEMENT_STOCK_DOWNLOAD", message) from None
    duration = None
    if mime == "video/mp4":
        from .video_editing_material_routes import metadata

        width, height, duration = await asyncio.to_thread(
            metadata, path, mime, settings
        )
    data_sha = await asyncio.to_thread(
        lambda: hashlib.sha256(path.read_bytes()).hexdigest()
    )
    material_id = str(uuid4())
    target = material_file(settings, material_id, mime)
    target.parent.mkdir(parents=True)
    shutil.copyfile(path, target)
    row = EditingMaterialRecord(
        id=material_id,
        request_id=str(body.request_id),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=str(body.project_id),
        kind=mime.split("/", 1)[0],
        mime=mime,
        sha256=data_sha,
        bytes=target.stat().st_size,
        # 规划按「名称与说明」匹配整句：名称写清是什么、配哪句话。
        # 模板可能把名称显示在画面上：短而有意义（说明里保留整句）。
        label=_short_label(body.sentence),
        description=body.sentence[:400],
        width=width,
        height=height,
        duration_ms=duration,
        origin="stock",
        provenance={
            "provider": candidate.provider,
            "provider_ref": candidate.provider_ref,
            "page_url": candidate.page_url,
            "download_url": candidate.download_url,
            "author": candidate.author,
            "author_url": candidate.author_url,
            "license": candidate.license,
            "license_url": candidate.license_url,
            "attribution": candidate.attribution,
            "sentence_index": body.sentence_index,
            "work_item_ref": body.work_item_ref,
            "token": body.token,
        },
    )
    from .video_editing_material_routes import commit_material

    return commit_material(session, row, target, identity)


# ---------------------------------------------------------------- AI images


@router.post("/ai-images/estimate")
async def ai_estimate(
    request: Request, workspace: VideoWorkspace, body: AiEstimateBody
) -> dict[str, Any]:
    settings = _settings(request)
    analysis = await asyncio.to_thread(analyze_script, settings, body.script_text)
    chosen = pick_paintable(analysis, body.max_images, body.exclude_sentences)
    credits = price(settings)
    return {
        "analysis_source": analysis.source,
        "items": chosen,
        "count": len(chosen),
        "credits_per_image": credits,
        "total_credits": (credits or 0) * len(chosen),
    }


def _spawn(request: Request, settings: Settings, ids: list[str]) -> None:
    from .video_editing_supplement_images import run_request

    factory = request.app.state.session_factory
    for request_id in ids:
        task = asyncio.get_running_loop().create_task(
            run_request(factory, settings, request_id)
        )
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


def _new_request(
    session: Session,
    settings: Settings,
    workspace: VideoWorkspace,
    project_id: str,
    work_item_ref: str | None,
    style: str,
    item: AiImageItem,
) -> EditingImageRequestRecord:
    from .video_credit_billing import hold
    from .video_editing_supplement_images import (
        cache_key,
        cached_material,
        prompt_for,
        store_image,
    )

    row = EditingImageRequestRecord(
        id=str(uuid4()),
        request_id=str(item.request_id),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=project_id,
        work_item_ref=work_item_ref,
        sentence_index=item.sentence_index,
        sentence=item.sentence,
        subject=item.subject,
        purpose=item.purpose,
        style=style,
        cache_key=cache_key(settings, prompt_for(style, item.purpose, item.subject)),
        status="queued",
    )
    session.add(row)
    session.flush()
    hit = cached_material(session, row)
    if hit is not None:
        try:
            payload = material_file(settings, hit.id, hit.mime).read_bytes()
            copy = store_image(
                session,
                settings,
                row,
                payload,
                model=(hit.provenance or {}).get("model", settings.image_model),
                prompt=prompt_for(style, item.purpose, item.subject),
                reused_from=hit.id,
            )
            row.material_id, row.status, row.reused = copy.id, "succeeded", True
            return row
        except OSError:
            pass
    hold(
        session,
        settings,
        workspace.workspace_id,
        "editing_auto_image",
        "video_editing_image",
        row.id,
    )
    return row


def expire_stale_images(
    session: Session, rows: list[EditingImageRequestRecord]
) -> None:
    """C5: an AI image whose background run died (API restart) fails after
    15 minutes and its hold is released, even when nothing was held (price
    unset) and the billing sweep never looks at it."""
    from .video_editing_supplement_images import STALE_AFTER

    now = utc_now()
    expired = []
    for row in rows:
        updated = row.updated_at
        if updated is not None and updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        if (
            row.status in {"queued", "running"}
            and updated is not None
            and now - updated > STALE_AFTER
        ):
            row.status, row.error_code = "failed", "AI_IMAGE_TIMEOUT"
            expired.append(row)
    if expired:
        session.commit()
        for row in expired:
            video_credits.reconcile_owner(session, "video_editing_image", row.id)
        session.commit()


@router.post("/ai-images", status_code=201)
async def ai_images(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    body: AiImagesBody,
) -> dict[str, Any]:
    from .video_editing_supplement_images import available, public

    require_workspace_write(workspace)
    settings = _settings(request)
    if not available(settings):
        raise ApiError(503, "SUPPLEMENT_AI_IMAGE_DISABLED", "AI 生成素材暂未开通。")
    project = str(body.project_id)
    own_project(session, workspace, project)
    if len({item.sentence_index for item in body.items}) != len(body.items):
        raise ApiError(422, "SUPPLEMENT_AI_IMAGE_DUPLICATE", "同一句只生成一张配图。")
    existing = session.scalars(
        select(EditingImageRequestRecord).where(
            EditingImageRequestRecord.project_id == project,
            EditingImageRequestRecord.owner_user_id == workspace.principal.user_id,
            EditingImageRequestRecord.request_id.in_(
                [str(i.request_id) for i in body.items]
            ),
        )
    ).all()
    if existing:
        if len(existing) == len(body.items):
            return {"items": [public(row) for row in existing]}
        raise ApiError(
            409, "EDITING_MATERIAL_REQUEST_REUSED", "素材请求编号已用于其他输入。"
        )
    expire_stale_images(
        session,
        list(
            session.scalars(
                select(EditingImageRequestRecord).where(
                    EditingImageRequestRecord.project_id == project,
                    EditingImageRequestRecord.owner_user_id
                    == workspace.principal.user_id,
                    EditingImageRequestRecord.work_item_ref == body.work_item_ref,
                    EditingImageRequestRecord.status.in_(("queued", "running")),
                )
            ).all()
        ),
    )
    active = session.scalars(
        select(EditingImageRequestRecord.sentence_index).where(
            EditingImageRequestRecord.project_id == project,
            EditingImageRequestRecord.owner_user_id == workspace.principal.user_id,
            EditingImageRequestRecord.work_item_ref == body.work_item_ref,
            EditingImageRequestRecord.status != "failed",
        )
    ).all()
    limit = settings.video_supplement_ai_image_max_per_video
    if len(set(active) | {item.sentence_index for item in body.items}) > limit:
        raise ApiError(
            422, "SUPPLEMENT_AI_IMAGE_LIMIT", f"每条视频最多生成 {limit} 张 AI 配图。"
        )
    rows = [
        _new_request(
            session, settings, workspace, project, body.work_item_ref, body.style, item
        )
        for item in body.items
    ]
    session.commit()
    _spawn(request, settings, [row.id for row in rows if row.status == "queued"])
    return {"items": [public(row) for row in rows]}


@router.get("/ai-images")
def ai_image_status(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID,
    ids: Annotated[list[str], Query(max_length=24)],
) -> dict[str, Any]:
    from .video_editing_supplement_images import public

    _settings(request)
    own_project(session, workspace, str(project_id))
    rows = session.scalars(
        select(EditingImageRequestRecord).where(
            EditingImageRequestRecord.project_id == str(project_id),
            EditingImageRequestRecord.owner_user_id == workspace.principal.user_id,
            EditingImageRequestRecord.id.in_(ids),
        )
    ).all()
    expire_stale_images(session, list(rows))
    materials = {
        row.id: material_response(row)
        for row in session.scalars(
            select(EditingMaterialRecord).where(
                EditingMaterialRecord.id.in_(
                    [r.material_id for r in rows if r.material_id]
                )
            )
        ).all()
    }
    return {
        "items": [
            {**public(row), "material": materials.get(row.material_id or "")}
            for row in rows
        ]
    }


@router.post("/ai-images/{image_id}/regenerate", status_code=201)
async def ai_regenerate(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    image_id: UUID,
    body: AiRegenerateBody,
) -> dict[str, Any]:
    from .video_editing_supplement_images import available, public

    require_workspace_write(workspace)
    settings = _settings(request)
    if not available(settings):
        raise ApiError(503, "SUPPLEMENT_AI_IMAGE_DISABLED", "AI 生成素材暂未开通。")
    old = session.get(EditingImageRequestRecord, str(image_id))
    if (
        old is None
        or old.workspace_id != workspace.workspace_id
        or (old.owner_user_id != workspace.principal.user_id)
    ):
        raise ApiError(404, "SUPPLEMENT_AI_IMAGE_NOT_FOUND", "未找到这张配图。")
    replay = session.scalar(
        select(EditingImageRequestRecord).where(
            EditingImageRequestRecord.project_id == old.project_id,
            EditingImageRequestRecord.owner_user_id == old.owner_user_id,
            EditingImageRequestRecord.request_id == str(body.request_id),
        )
    )
    if replay is not None:
        return public(replay)
    item = AiImageItem(
        request_id=body.request_id,
        sentence_index=old.sentence_index,
        sentence=old.sentence,
        subject=body.subject or old.subject,
        purpose=old.purpose,  # type: ignore[arg-type]
    )
    # A regenerate is a new image: when the prompt is unchanged, salt the
    # cache key so the user gets a different picture (and is charged once).
    row = _new_request(
        session, settings, workspace, old.project_id, old.work_item_ref, old.style, item
    )
    if row.reused and body.subject in (None, old.subject):
        session.rollback()
        row = EditingImageRequestRecord(
            id=str(uuid4()),
            request_id=str(body.request_id),
            workspace_id=old.workspace_id,
            owner_user_id=old.owner_user_id,
            project_id=old.project_id,
            work_item_ref=old.work_item_ref,
            sentence_index=old.sentence_index,
            sentence=old.sentence,
            subject=old.subject,
            purpose=old.purpose,
            style=old.style,
            cache_key=hashlib.sha256(
                f"{old.cache_key}|{body.request_id}".encode()
            ).hexdigest(),
            status="queued",
        )
        session.add(row)
        session.flush()
        from .video_credit_billing import hold

        hold(
            session,
            settings,
            workspace.workspace_id,
            "editing_auto_image",
            "video_editing_image",
            row.id,
        )
    session.commit()
    if row.status == "queued":
        _spawn(request, settings, [row.id])
    return public(row)


# ---------------------------------------------------------------- delete


class MaterialPlacementBody(StrictVideoModel):
    sentence_index: int | None = Field(default=None, ge=0, le=60)
    sentence: str | None = Field(default=None, min_length=1, max_length=300)


AUTO_DESCRIPTION = "商家上传的补充素材，放在画面最贴合的句子"


def _own_material(
    session: Session, workspace: VideoWorkspace, project_id: UUID, material_id: UUID
) -> EditingMaterialRecord:
    row = session.scalar(
        select(EditingMaterialRecord).where(
            *material_scope(workspace, project_id),
            EditingMaterialRecord.id == str(material_id),
        )
    )
    if row is None:
        raise ApiError(404, "EDITING_MATERIAL_NOT_FOUND", "未找到本项目的补充素材。")
    return row


def _require_unused(
    session: Session, project_id: UUID, row: EditingMaterialRecord, verb: str
) -> None:
    """Frozen planning snapshots bind the material card: never change it."""
    marker = f"material-{row.id}"
    plans: Sequence[Any] = session.scalars(
        select(EditingPlanningTaskRecord.snapshot).where(
            EditingPlanningTaskRecord.project_id == str(project_id)
        )
    ).all()
    if any(marker in json.dumps(snapshot or {}) for snapshot in plans):
        raise ApiError(
            409,
            "EDITING_MATERIAL_IN_USE",
            f"这个素材已用在剪辑里，不能{verb}；可以重新上传一份。",
        )


@material_router.put("/{material_id}/placement")
def place_material(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID,
    material_id: UUID,
    body: MaterialPlacementBody,
) -> dict[str, Any]:
    """「我来指定句子」：把素材说明改成那一句原文，规划按它放置；空 = 自动。"""
    require_workspace_write(workspace)
    enabled(request)
    own_project(session, workspace, str(project_id))
    row = _own_material(session, workspace, project_id, material_id)
    if row.origin is not None:
        raise ApiError(
            422, "EDITING_MATERIAL_PLACEMENT", "只有自己上传的素材可以指定句子。"
        )
    if (body.sentence_index is None) != (body.sentence is None):
        raise ApiError(422, "EDITING_MATERIAL_PLACEMENT", "请选择要放的句子。")
    description = (
        f"用于第 {body.sentence_index + 1} 句：{body.sentence.strip()}"[:400]
        if body.sentence_index is not None and body.sentence
        else AUTO_DESCRIPTION
    )
    if row.description != description:
        _require_unused(session, project_id, row, "改句子")
        row.description = description
        session.commit()
    return material_response(row)


@material_router.delete("/{material_id}", status_code=204)
def delete_material(
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    project_id: UUID,
    material_id: UUID,
) -> Response:
    require_workspace_write(workspace)
    settings = enabled(request)
    own_project(session, workspace, str(project_id))
    row = _own_material(session, workspace, project_id, material_id)
    _require_unused(session, project_id, row, "删除")
    path = material_file(settings, row.id, row.mime)
    session.delete(row)
    session.commit()
    path.unlink(missing_ok=True)
    with suppress(OSError):
        path.parent.rmdir()
    return Response(status_code=204)
