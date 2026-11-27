"""成片 step: AI covers for finished videos, and saving the final work (W5).

``POST /cover-candidates`` makes two candidates for one video, in two
structurally different layouts: slot 0 on the real keyframe (the face is never
redrawn, free) and slot 1 on an AI repaint of it (``cover_generate``, 7 credits
by default). The title is always typeset by ``video_cover_compose``; a
candidate is ``ready`` only when every check passed, and only a ready AI
candidate is charged. When the AI background fails, slot 1 falls back to the
real frame in its own layout and its hold is released.

``POST /cover-candidates/{id}/retext`` re-typesets a new cover text on the same
background for free. ``POST /work-items/{id}/finish`` saves the chosen cover
and final title/body onto the work item (contract C2) and marks it done.
"""

from __future__ import annotations

import hashlib
import io
import logging
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import Field
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from . import video_cover_compose as compose
from . import video_cover_skill as skill
from . import video_credit_billing as video_credits
from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .errors import ApiError
from .video_cover_image_client import (
    CoverImageClient,
    CoverImageError,
    HttpCoverImageClient,
)
from .video_cover_models import VideoCoverCandidateRecord
from .video_editing_task_models import EditingSourceRecord, EditingTaskRecord
from .video_generation_models import VideoGenerationRecord
from .video_studio_routes import VideoWorkspace
from .video_studio_schemas import StrictVideoModel
from .video_work_models import VideoWorkItemRecord
from .video_work_routes import WorkItemPatch, WorkItemResponse, patch_item

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}", tags=["video-covers"]
)

Platform = Literal["douyin", "xiaohongshu"]
TITLE_LIMITS = {"douyin": 30, "xiaohongshu": 20}
# A run interrupted by an API restart is resumed at startup (recover_interrupted);
# this only catches rows nothing resumed.
STALE_SECONDS = 30 * 60

MESSAGES = {
    "COVER_SOURCE_UNREADABLE": "视频读不出来，换一条视频试试。",
    "COVER_TEXT_DOES_NOT_FIT": "封面大字太长，放不下，请删减几个字。",
    "COVER_CHECK_FAILED": "封面核对没有通过，请换一批。",
    "COVER_IMAGE_NOT_CONFIGURED": "AI 封面服务尚未配置，已改用视频画面。",
    "COVER_IMAGE_TIMEOUT": "AI 封面生成超时，已改用视频画面，未扣积分。",
    "COVER_IMAGE_UNAVAILABLE": "AI 封面服务暂时不可用，已改用视频画面，未扣积分。",
    "COVER_IMAGE_REJECTED": "AI 封面没有生成成功，已改用视频画面，未扣积分。",
    "COVER_IMAGE_INVALID": "AI 封面没有生成成功，已改用视频画面，未扣积分。",
    "COVER_INTERRUPTED": "封面生成被中断，请重新生成，未扣积分。",
    "COVER_FAILED": "封面生成失败，请重试，未扣积分。",
}


class CoverGenerateRequest(StrictVideoModel):
    request_id: UUID
    work_item_id: str | None = Field(default=None, max_length=40)
    editing_task_id: UUID | None = None
    generation_task_id: UUID | None = None
    cover_text: str = Field(min_length=1, max_length=compose.MAX_TEXT_CHARS)
    highlight: str | None = Field(default=None, max_length=compose.MAX_TEXT_CHARS)
    platform: Platform = "douyin"
    round: int = Field(default=0, ge=0, le=50)


class CoverRetextRequest(StrictVideoModel):
    request_id: UUID
    cover_text: str = Field(min_length=1, max_length=compose.MAX_TEXT_CHARS)
    highlight: str | None = Field(default=None, max_length=compose.MAX_TEXT_CHARS)


class CoverChecks(StrictVideoModel):
    text_exact: bool
    glyphs_ok: bool
    face_clear: bool
    design_colors_ok: bool
    size_ok: bool
    face_detected: bool
    picture_cool_hint: bool


class CoverCandidateResponse(StrictVideoModel):
    id: str
    request_id: str
    slot: int
    round: int
    parent_id: str | None
    work_item_id: str | None
    source_kind: Literal["editing", "generation"]
    source_id: str
    platform: Platform
    cover_text: str
    highlight: str | None
    background: Literal["frame", "ai"]
    background_label: str
    layout: str | None
    status: Literal["queued", "running", "ready", "failed"]
    error_code: str | None
    message: str | None
    checks: CoverChecks | None
    credits: int | None
    image_url: str | None
    thumb_url: str | None
    created_at: datetime


class CoverFinishRequest(StrictVideoModel):
    expected_version: int = Field(ge=1)
    cover_candidate_id: str = Field(max_length=40)
    publish_title: str = Field(min_length=1, max_length=60)
    publish_body: str = Field(default="", max_length=2000)


# ------------------------------------------------------------------ helpers


def image_client(request: Request) -> CoverImageClient:
    client = getattr(request.app.state, "video_cover_image_client", None)
    return client or HttpCoverImageClient(request.app.state.settings)


def covers_root(settings: Any) -> Path:
    return Path(settings.video_media_dir) / "covers"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _owner(workspace: WorkspaceContext) -> tuple[str, str]:
    return workspace.workspace_id, workspace.principal.user_id


def _held_credits(session: Session, row: VideoCoverCandidateRecord) -> int | None:
    holds = video_credits._holds(session, "video_cover", row.id, "cover_generate")
    hold = next(iter(holds), None)
    if hold is None:
        return None
    if hold.status == video_credits.SETTLED:
        return hold.settled_credits or hold.reserved_credits
    if hold.status == video_credits.ACTIVE:
        return hold.reserved_credits
    return 0


def response(
    session: Session, row: VideoCoverCandidateRecord
) -> CoverCandidateResponse:
    root = f"/api/v1/video-studio/workspaces/{row.workspace_id}"
    base = f"{root}/cover-candidates/{row.id}/image"
    ready = row.status == "ready"
    checks = None
    if row.checks:
        checks = CoverChecks(
            **{k: bool(row.checks.get(k)) for k in CoverChecks.model_fields}
        )
    message = MESSAGES.get(row.error_code or "") if row.error_code else None
    return CoverCandidateResponse(
        id=row.id,
        request_id=row.request_id,
        slot=row.slot,
        round=row.round,
        parent_id=row.parent_id,
        work_item_id=row.work_item_id,
        source_kind=row.source_kind,  # type: ignore[arg-type]
        source_id=row.source_id,
        platform=row.platform,  # type: ignore[arg-type]
        cover_text=row.cover_text,
        highlight=row.highlight,
        background=row.background,  # type: ignore[arg-type]
        background_label="AI 重绘" if row.background == "ai" else "视频画面",
        layout=row.layout,
        status=row.status,  # type: ignore[arg-type]
        error_code=row.error_code,
        message=message,
        checks=checks,
        credits=_held_credits(session, row),
        image_url=base if ready else None,
        thumb_url=base + "?view=thumb" if ready else None,
        created_at=_aware(row.created_at),
    )


def _validate_text(text: str, highlight: str | None) -> tuple[str, str | None]:
    text = compose.normalise_cover_text(text)
    if not text:
        raise ApiError(422, "COVER_TEXT_REQUIRED", "请填写封面大字。")
    missing = compose.missing_glyphs(text)
    if missing:
        raise ApiError(
            422,
            "COVER_TEXT_GLYPHS",
            "封面大字里有字体显示不了的字符："
            + " ".join(missing)
            + "，请删掉后再生成。",
            {"characters": missing},
        )
    highlight = compose.normalise_cover_text(highlight or "") or None
    if highlight and highlight.replace(" ", "") not in text.replace(" ", ""):
        raise ApiError(
            422, "COVER_HIGHLIGHT_INVALID", "加强的词必须是封面大字里连续的一段。"
        )
    return text, highlight


def _own_item(
    session: Session, workspace: WorkspaceContext, item_id: str
) -> VideoWorkItemRecord:
    row = session.get(VideoWorkItemRecord, item_id)
    if not row or (row.workspace_id, row.owner_user_id) != _owner(workspace):
        raise ApiError(404, "VIDEO_WORK_ITEM_NOT_FOUND", "未找到这条作品。")
    return row


def resolve_source(
    session: Session, workspace: WorkspaceContext, body: CoverGenerateRequest
) -> tuple[str, str, Path]:
    """(kind, id, video path): a completed edit's source clip, else a finished 口播."""

    editing_id = str(body.editing_task_id) if body.editing_task_id else None
    generation_id = str(body.generation_task_id) if body.generation_task_id else None
    if body.work_item_id:
        item = _own_item(session, workspace, body.work_item_id)
        editing_id = editing_id or item.editing_task_id
        generation_id = generation_id or item.generation_task_id
        ref = item.source_video_ref or {}
        if not generation_id and ref.get("kind") == "talking":
            generation_id = ref.get("id")
    owner = _owner(workspace)
    if editing_id:
        task = session.get(EditingTaskRecord, editing_id)
        if (
            task
            and (task.workspace_id, task.owner_user_id) == owner
            and task.status == "completed"
        ):
            source = session.get(EditingSourceRecord, task.source_id)
            candidates = [Path(source.media_path)] if source else []
            from .video_editing_task_models import EditingArtifactRecord

            final = session.scalar(
                select(EditingArtifactRecord).where(
                    EditingArtifactRecord.task_id == task.id,
                    EditingArtifactRecord.role == "final",
                )
            )
            if final:
                candidates.append(Path(final.path))
            for path in candidates:
                if path.is_file():
                    return "editing", task.id, path
    if generation_id:
        job = session.get(VideoGenerationRecord, generation_id)
        if (
            job
            and (job.workspace_id, job.owner_user_id) == owner
            and job.status == "completed"
        ):
            path = Path((job.details or {}).get("result_path") or "")
            if path.is_file():
                return "generation", job.id, path
    raise ApiError(
        422,
        "COVER_SOURCE_NOT_READY",
        "这条视频还没有完成，完成剪辑或口播后再生成封面。",
    )


def _fingerprint(payload: dict[str, Any]) -> str:
    import json

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


# --------------------------------------------------------------- processing


def _save(image: Image.Image, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=92, optimize=True)
    return str(path)


def _to_canvas(image: Image.Image) -> Image.Image:
    w, h = image.size
    target = compose.CANVAS[0] / compose.CANVAS[1]
    if abs(w / h - target) > 0.01:
        if w / h > target:
            nw = round(h * target)
            image = image.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = round(w / target)
            image = image.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return image.convert("RGB").resize(compose.CANVAS, Image.Resampling.LANCZOS)


def _finish(
    root: Path,
    row: VideoCoverCandidateRecord,
    background: Image.Image,
    face: compose.Box | None,
    layouts: list[compose.Layout],
    kind: str,
    extra: dict[str, Any],
) -> None:
    root = root / row.id
    result, checks = compose.compose(
        background, row.cover_text, layouts, face, row.highlight
    )
    files = {"background": _save(background, root / "background.jpg")}
    files.update(compose.save_views(result.image, face, root))
    row.background = kind
    row.layout = result.layout
    row.files = files
    row.checks = checks.as_dict()
    row.params = {
        **row.params,
        **extra,
        "face": list(face) if face else None,
        "lines": result.lines,
        "font_size": result.font_size,
        "tone": result.tone,
        "design_colors": result.design_colors,
        "zone": list(result.zone),
    }
    row.status = "ready"
    row.error_code = None


def process_request(
    factory: sessionmaker[Session],
    settings: Any,
    client: CoverImageClient,
    row_ids: list[str],
    video: str,
) -> None:
    """Keyframe once, then the real-frame candidate, then the AI candidate."""

    root = covers_root(settings)
    work = root / ("work-" + row_ids[0])
    work.mkdir(parents=True, exist_ok=True)
    try:
        with factory() as session:
            found = [session.get(VideoCoverCandidateRecord, rid) for rid in row_ids]
            rows = [
                r for r in found if r is not None and r.status in {"queued", "running"}
            ]
            if not rows:
                return
            for row in rows:
                row.status = "running"
            session.commit()
            try:
                key = compose.pick_keyframe(Path(video), work)
            except compose.CoverComposeError as exc:
                for row in rows:
                    row.status, row.error_code = "failed", exc.code
                session.commit()
                return
            frame, face = compose.crop_to_canvas(
                key.image, key.face, rows[0].cover_text
            )
            previous = tuple(rows[0].params.get("previous_layouts") or ())
            # The real frame can only use layouts that fit around the face as it
            # is; the AI repaint is asked to re-frame for a different layout.
            fitting = compose.choose_layouts(face, previous, rows[0].cover_text)
            preferred = compose.choose_layouts(face, previous)
            frame_layout: str | None = None
            frame_bg = compose.warm_grade(frame)
            keyframe_info = {
                "keyframe_at": key.at,
                "keyframe_score": round(key.score, 4),
            }
            for row in rows:
                started = time.monotonic()
                shift = row.slot % len(fitting)
                own_layouts = fitting[shift:] + fitting[:shift]
                try:
                    if row.background == "frame":
                        _finish(
                            root,
                            row,
                            frame_bg,
                            face,
                            own_layouts,
                            "frame",
                            keyframe_info,
                        )
                        frame_layout = row.layout
                    else:
                        asked = [x for x in preferred if x != frame_layout]
                        asked += [x for x in fitting if x not in asked]
                        _ai_candidate(
                            root,
                            row,
                            client,
                            frame,
                            face,
                            asked,
                            own_layouts,
                            frame_bg,
                            keyframe_info,
                        )
                except compose.CoverComposeError as exc:
                    row.status, row.error_code = "failed", exc.code
                except Exception:
                    logger.exception("video_cover_failed id=%s", row.id)
                    row.status, row.error_code = "failed", "COVER_FAILED"
                row.receipt = {
                    **row.receipt,
                    "seconds": round(time.monotonic() - started, 2),
                    "skill": skill.SKILL_ID,
                    "skill_version": skill.skill_version(),
                }
                session.commit()
                video_credits.reconcile_owner(session, "video_cover", row.id)
                session.commit()
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _ai_candidate(
    root: Path,
    row: VideoCoverCandidateRecord,
    client: CoverImageClient,
    frame: Image.Image,
    face: compose.Box | None,
    layouts: list[compose.Layout],
    fallback: list[compose.Layout],
    frame_bg: Image.Image,
    keyframe_info: dict[str, Any],
) -> None:
    """``layouts``: what the repaint is framed for; ``fallback``: real-frame order."""

    face_on_right = face is not None and (face[0] + face[2]) / 2 > compose.CANVAS[0] / 2
    zone_key = skill.zone_key(layouts[0], face_on_right)
    dims = skill.choose_dimensions(
        row.params.get("topic") or row.cover_text, rotate=row.round
    )
    prompt = skill.build_prompt(
        row.params.get("topic") or row.cover_text, zone_key, dims
    )
    buffer = io.BytesIO()
    frame.save(buffer, "PNG")
    try:
        result = client.edit(
            buffer.getvalue(), prompt, idempotency_key=f"cover-{row.id}"
        )
    except CoverImageError as exc:
        # Fall back to the real frame in this slot's own layout; nothing is charged.
        row.receipt = {**row.receipt, "ai_error_code": exc.code}
        _finish(
            root,
            row,
            frame_bg,
            face,
            fallback,
            "frame",
            {**keyframe_info, "fallback_from": "ai"},
        )
        row.error_code = exc.code  # shown as a note; the candidate itself is ready
        return
    background = _to_canvas(result.image)
    redetected = compose.detect_face(background)
    new_face = redetected[0] if redetected else face
    row.receipt = {
        **row.receipt,
        "model_requested": result.model_requested,
        "model_reported": result.model_reported,
        "prompt_sha256": skill.prompt_hash(prompt),
    }
    _finish(
        root,
        row,
        background,
        new_face,
        layouts,
        "ai",
        {
            **keyframe_info,
            "dimensions": dims.__dict__,
            "face_redetected": bool(redetected),
        },
    )


# ------------------------------------------------------------------- routes


def _rows_for_request(
    session: Session, workspace: WorkspaceContext, request_id: str
) -> list[VideoCoverCandidateRecord]:
    return list(
        session.scalars(
            select(VideoCoverCandidateRecord)
            .where(
                VideoCoverCandidateRecord.workspace_id == workspace.workspace_id,
                VideoCoverCandidateRecord.owner_user_id == workspace.principal.user_id,
                VideoCoverCandidateRecord.request_id == request_id,
            )
            .order_by(VideoCoverCandidateRecord.slot)
        )
    )


@router.post("/cover-candidates", response_model=list[CoverCandidateResponse])
def generate(
    body: CoverGenerateRequest,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> list[CoverCandidateResponse]:
    require_workspace_write(workspace)
    text, highlight = _validate_text(body.cover_text, body.highlight)
    payload = body.model_dump(mode="json") | {
        "cover_text": text,
        "highlight": highlight,
    }
    fingerprint = _fingerprint(payload)
    existing = _rows_for_request(session, workspace, str(body.request_id))
    if existing:
        if existing[0].request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求标识已用于其他内容。")
        return [response(session, row) for row in existing]
    kind, source_id, video = resolve_source(session, workspace, body)
    item = (
        _own_item(session, workspace, body.work_item_id) if body.work_item_id else None
    )
    previous = (
        session.scalars(
            select(VideoCoverCandidateRecord.layout)
            .where(
                VideoCoverCandidateRecord.workspace_id == workspace.workspace_id,
                VideoCoverCandidateRecord.owner_user_id == workspace.principal.user_id,
                VideoCoverCandidateRecord.source_kind == kind,
                VideoCoverCandidateRecord.source_id == source_id,
                VideoCoverCandidateRecord.status == "ready",
            )
            .order_by(VideoCoverCandidateRecord.created_at.desc())
            .limit(2)
        ).all()
        if body.round
        else []
    )
    topic = " ".join(
        filter(
            None,
            [
                item.publish_title if item else "",
                (item.script_text or "")[:120] if item else "",
                text,
            ],
        )
    )
    rows = []
    for slot, kind_ in ((0, "frame"), (1, "ai")):
        rows.append(
            VideoCoverCandidateRecord(
                id=str(uuid4()),
                workspace_id=workspace.workspace_id,
                owner_user_id=workspace.principal.user_id,
                request_id=str(body.request_id),
                request_hash=fingerprint,
                slot=slot,
                work_item_id=body.work_item_id,
                source_kind=kind,
                source_id=source_id,
                platform=body.platform,
                cover_text=text,
                highlight=highlight,
                background=kind_,
                round=body.round,
                status="queued",
                params={
                    "topic": topic,
                    "previous_layouts": [p for p in previous if p],
                    "video": str(video),
                },
                checks={},
                files={},
                receipt={},
            )
        )
    session.add_all(rows)
    try:
        session.flush()
        video_credits.hold(
            session,
            request.app.state.settings,
            workspace.workspace_id,
            "cover_generate",
            "video_cover",
            rows[1].id,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = _rows_for_request(session, workspace, str(body.request_id))
        if not existing or existing[0].request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求冲突。") from None
        return [response(session, row) for row in existing]
    background.add_task(
        process_request,
        request.app.state.session_factory,
        request.app.state.settings,
        image_client(request),
        [row.id for row in rows],
        str(video),
    )
    return [response(session, row) for row in rows]


def _own_candidate(
    session: Session, workspace: WorkspaceContext, candidate_id: str
) -> VideoCoverCandidateRecord:
    row = session.get(VideoCoverCandidateRecord, candidate_id)
    if not row or (row.workspace_id, row.owner_user_id) != _owner(workspace):
        raise ApiError(404, "COVER_NOT_FOUND", "未找到这张封面。")
    return row


def _expire_stale(session: Session, rows: list[VideoCoverCandidateRecord]) -> None:
    """A worker that died mid-run must not leave a spinner (or a hold) forever."""

    now = datetime.now(UTC)
    changed = False
    for row in rows:
        if (
            row.status in {"queued", "running"}
            and (now - _aware(row.updated_at)).total_seconds() > STALE_SECONDS
        ):
            row.status, row.error_code = "failed", "COVER_INTERRUPTED"
            changed = True
    if changed:
        session.commit()
        for row in rows:
            if row.error_code == "COVER_INTERRUPTED":
                video_credits.reconcile_owner(session, "video_cover", row.id)
        session.commit()


@router.get("/cover-candidates", response_model=list[CoverCandidateResponse])
def list_candidates(
    workspace: VideoWorkspace,
    session: SessionDependency,
    work_item_id: Annotated[str | None, Query(max_length=40)] = None,
    editing_task_id: UUID | None = None,
    generation_task_id: UUID | None = None,
    ids: Annotated[str | None, Query(max_length=8200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 40,
) -> list[CoverCandidateResponse]:
    query = select(VideoCoverCandidateRecord).where(
        VideoCoverCandidateRecord.workspace_id == workspace.workspace_id,
        VideoCoverCandidateRecord.owner_user_id == workspace.principal.user_id,
    )
    filters = []
    if work_item_id:
        filters.append(VideoCoverCandidateRecord.work_item_id == work_item_id)
    if editing_task_id:
        filters.append(
            (VideoCoverCandidateRecord.source_kind == "editing")
            & (VideoCoverCandidateRecord.source_id == str(editing_task_id))
        )
    if generation_task_id:
        filters.append(
            (VideoCoverCandidateRecord.source_kind == "generation")
            & (VideoCoverCandidateRecord.source_id == str(generation_task_id))
        )
    if ids:
        wanted = [value for value in ids.split(",") if value][:200]
        filters.append(VideoCoverCandidateRecord.id.in_(wanted))
    if not filters:
        raise ApiError(422, "COVER_FILTER_REQUIRED", "请指定作品或视频。")
    rows = list(
        session.scalars(
            query.where(or_(*filters))
            .order_by(
                VideoCoverCandidateRecord.created_at.desc(),
                VideoCoverCandidateRecord.slot,
            )
            .limit(limit)
        )
    )
    _expire_stale(session, rows)
    return [response(session, row) for row in rows]


@router.get("/cover-candidates/{candidate_id}", response_model=CoverCandidateResponse)
def get_candidate(
    candidate_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> CoverCandidateResponse:
    row = _own_candidate(session, workspace, candidate_id)
    _expire_stale(session, [row])
    return response(session, row)


@router.get("/cover-candidates/{candidate_id}/image")
def candidate_image(
    candidate_id: str,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
    view: Literal["cover", "thumb", "face"] = "cover",
    download: bool = False,
) -> FileResponse:
    row = _own_candidate(session, workspace, candidate_id)
    stored = row.files.get(view) if row.status == "ready" else None
    root = (covers_root(request.app.state.settings) / row.id).resolve()
    path = Path(stored).resolve() if stored else None
    if not path or root not in path.parents or not path.is_file():
        raise ApiError(404, "COVER_IMAGE_NOT_FOUND", "封面图片暂不可用。")
    return FileResponse(
        path,
        media_type="image/jpeg",
        filename=f"封面-{row.cover_text[:12]}.jpg" if download else None,
        content_disposition_type="attachment" if download else "inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post(
    "/cover-candidates/{candidate_id}/retext", response_model=CoverCandidateResponse
)
def retext(
    candidate_id: str,
    body: CoverRetextRequest,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> CoverCandidateResponse:
    """Same background, new cover text: free, synchronous (well under a second)."""

    require_workspace_write(workspace)
    parent = _own_candidate(session, workspace, candidate_id)
    text, highlight = _validate_text(body.cover_text, body.highlight)
    fingerprint = _fingerprint(
        {"parent": parent.id, "cover_text": text, "highlight": highlight}
    )
    existing = _rows_for_request(session, workspace, str(body.request_id))
    if existing:
        if existing[0].request_hash != fingerprint:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "请求标识已用于其他内容。")
        return response(session, existing[0])
    source = Path(parent.files.get("background") or "")
    if parent.status != "ready" or not source.is_file():
        raise ApiError(409, "COVER_NOT_READY", "这张封面还没有生成好。")
    row = VideoCoverCandidateRecord(
        id=str(uuid4()),
        workspace_id=parent.workspace_id,
        owner_user_id=parent.owner_user_id,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        slot=0,
        work_item_id=parent.work_item_id,
        source_kind=parent.source_kind,
        source_id=parent.source_id,
        platform=parent.platform,
        cover_text=text,
        highlight=highlight,
        background=parent.background,
        round=parent.round,
        parent_id=parent.id,
        status="running",
        params={"topic": parent.params.get("topic")},
        checks={},
        files={},
        receipt={},
    )
    session.add(row)
    session.flush()
    with Image.open(source) as opened:
        background_image = opened.convert("RGB")
    stored_face = parent.params.get("face")
    face: compose.Box | None = (
        (stored_face[0], stored_face[1], stored_face[2], stored_face[3])
        if stored_face
        else None
    )
    # Same layout as the parent first, then the usual pair for this face.
    known: list[compose.Layout] = ["top", "bottom", "side", "center"]
    layouts = [layout for layout in known if layout == parent.layout]
    fitting = compose.choose_layouts(face, text=text)
    layouts += [x for x in fitting if x not in layouts]
    try:
        _finish(
            covers_root(request.app.state.settings),
            row,
            background_image,
            face,
            layouts,
            parent.background,
            {"retext_of": parent.id},
        )
    except compose.CoverComposeError as exc:
        session.rollback()
        raise ApiError(422, exc.code, MESSAGES.get(exc.code, exc.message)) from None
    session.commit()
    return response(session, row)


@router.post("/work-items/{item_id}/finish", response_model=WorkItemResponse)
def finish_item(
    item_id: str,
    body: CoverFinishRequest,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> WorkItemResponse:
    """Save the chosen cover and the final title/body; the work becomes 已完成."""

    require_workspace_write(workspace)
    item = _own_item(session, workspace, item_id)
    cover = _own_candidate(session, workspace, body.cover_candidate_id)
    if cover.status != "ready":
        raise ApiError(409, "COVER_NOT_READY", "这张封面还没有生成好。")
    matches = cover.work_item_id == item.id or (
        (cover.source_kind == "editing" and cover.source_id == item.editing_task_id)
        or (
            cover.source_kind == "generation"
            and cover.source_id == item.generation_task_id
        )
    )
    if not matches:
        raise ApiError(422, "COVER_ITEM_MISMATCH", "这张封面不是这条视频的。")
    patch = WorkItemPatch(
        expected_version=body.expected_version,
        publish_title=body.publish_title.strip(),
        publish_body=body.publish_body,
        cover_asset_id=cover.id,
        stage="done",
        status="succeeded",
    )
    return patch_item(item_id, patch, workspace, session)


def recover_interrupted(
    factory: sessionmaker[Session],
    settings: Any,
    client: CoverImageClient,
    started: datetime,
) -> int:
    """Resume generate requests an API restart cut off (rows not touched since).

    The AI slot reuses its idempotency key and its credit hold, so a resumed
    request is still charged at most once.
    """

    with factory() as session:
        rows = session.scalars(
            select(VideoCoverCandidateRecord)
            .where(
                VideoCoverCandidateRecord.status.in_(("queued", "running")),
                VideoCoverCandidateRecord.parent_id.is_(None),
                VideoCoverCandidateRecord.updated_at < started,
            )
            .order_by(
                VideoCoverCandidateRecord.created_at, VideoCoverCandidateRecord.slot
            )
            .limit(200)
        ).all()
        groups: dict[tuple[str, str, str], list[VideoCoverCandidateRecord]] = {}
        for row in rows:
            groups.setdefault(
                (row.workspace_id, row.owner_user_id, row.request_id), []
            ).append(row)
        jobs = []
        for group in groups.values():
            video = group[0].params.get("video")
            if not video or not Path(video).is_file():
                for row in group:
                    row.status, row.error_code = "failed", "COVER_INTERRUPTED"
                continue
            for row in group:
                row.status = "queued"
            jobs.append(([row.id for row in group], video))
        session.commit()
        for group in groups.values():
            for row in group:
                if row.status == "failed":
                    video_credits.reconcile_owner(session, "video_cover", row.id)
        session.commit()
    for ids, video in jobs:
        process_request(factory, settings, client, ids, video)
    return len(jobs)


def start_recovery(application: Any) -> None:
    """Called from the API lifespan: resume interrupted covers in the background."""

    import threading

    started = datetime.now(UTC)

    def run() -> None:
        try:
            client = getattr(
                application.state, "video_cover_image_client", None
            ) or HttpCoverImageClient(application.state.settings)
            count = recover_interrupted(
                application.state.session_factory,
                application.state.settings,
                client,
                started,
            )
            if count:
                logger.info("video_cover_recovered requests=%s", count)
        except Exception:
            logger.exception("video_cover_recovery_failed")

    threading.Thread(target=run, name="video-cover-recovery", daemon=True).start()
