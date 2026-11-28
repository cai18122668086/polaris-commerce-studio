"""文案库（契约 C1）：每条 = 发布标题 + 发布正文 + 口播稿。

* 写稿通过检查、保存成文稿的那一刻自动入库（``ingest_draft``），幂等键是
  「运行 id + 版本序号」，同一份文稿无论从哪条路保存也只入库一次。
* 用户改了再存是同一条的新版本（``revision`` + ``history``），不是新条目。
* 老的文案库（``video_script_versions`` 里 kind=library 的快照）在主人第一次
  打开文案库时镜像进来（``legacy_version_id``），没有标题和正文也能正常显示。
* 列表一次可取多条、可按 id 批量取（给口播页 ``?scripts=id1,id2``）。
* 第三轮（开关 ``POLARIS_VIDEO_WRITING_BRIEF_V2`` 打开的用户）：写完不再自动入库，
  结果页勾选后 ``POST /script-library/batch`` 一次存入多份文稿（幂等，同一文稿
  只一条）；文案库可 ``batch-delete`` 一次删多条，可按生成批次（``run_id``）和
  来源筛选，``GET /script-library/runs`` 给分组视图。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from pydantic import Field, StringConstraints
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import video_credit_billing as video_credits
from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .errors import ApiError
from .models import utc_now
from .video_assistance import provider
from .video_assistance_models import VideoAssistanceRecord
from .video_studio_access import require_video_studio_access
from .video_studio_models import VideoProjectRecord, VideoScriptVersionRecord
from .video_studio_routes import VideoWorkspace, scope
from .video_studio_schemas import StrictVideoModel, VideoProjectContent
from .video_work_models import VideoWorkItemRecord
from .video_writing_models import VideoScriptLibraryEntry, VideoWritingDocument

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}",
    tags=["video-script-library"],
    dependencies=[Depends(require_video_studio_access)],
)

Source = Literal["auto_writing", "manual", "imported"]
Platform = Literal["douyin", "xiaohongshu"]
MAX_IDS = 50
# 一次批量存入 / 删除最多多少条（结果页最多 10 条，文案库一页最多 100 条）。
MAX_BATCH = 100
AUTO_KIND = "auto_writing"
ID_PATTERN = r"[0-9A-Za-z-]{1,40}"
OLDER_LABEL = "更早的"
HISTORY_KEPT = 20
DEFAULT_NAME = "未命名视频"
# Same estimate as the result cards: about 4.8 spoken characters a second.
CHARS_PER_SECOND = 4.8


def spoken_chars(text: str) -> int:
    return len(re.findall(r"[^\W_]", text))


def first_sentence(text: str, limit: int = 24) -> str:
    for piece in re.split(r"[。！？!?\n]+", text):
        piece = piece.strip(" ，,、；;：:")
        if piece:
            return piece if len(piece) <= limit else piece[:limit] + "…"
    return ""


class LibraryAngle(StrictVideoModel):
    id: str
    name: str


class LibraryEntry(StrictVideoModel):
    id: str
    created_at: datetime
    updated_at: datetime
    source: Source
    platform: Platform | Literal[""]
    publish_title: str
    publish_body: str
    script: str
    benchmark_refs: list[dict[str, Any]]
    revision: int
    project_id: str | None
    writing_document_id: str | None
    # Derived for display: the title, or the script's first sentence for old
    # entries without one; spoken length and estimated seconds.
    display_title: str
    script_chars: int
    script_seconds: int
    # 第三轮：来自哪次爆款文案（旧条目为空）、哪个角度、是否已用于口播。
    run_id: str | None = None
    angle: LibraryAngle | None = None
    used_for_talking: bool = False


class LibraryPage(StrictVideoModel):
    items: list[LibraryEntry]
    total: int
    limit: int
    offset: int
    # ids asked for that are not (or no longer) in this user's library
    missing_ids: list[str] = Field(default_factory=list)


class LibraryWrite(StrictVideoModel):
    publish_title: str = Field(default="", max_length=80)
    publish_body: str = Field(default="", max_length=2000)
    script: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)
    ]
    platform: Platform | Literal[""] = ""


class LibraryCreate(LibraryWrite):
    request_id: UUID
    # 「存入文案库」：一版写好的稿子（旧版本没自动入库）。同一份文稿只存一条，
    # 重复点击或刷新后再点都返回同一条。
    writing_document_id: UUID | None = None
    source: Literal["manual", "auto_writing"] = "manual"


class LibraryUpdate(LibraryWrite):
    expected_revision: int = Field(ge=1)


def aware(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def clean_angle(value: Any) -> dict[str, str] | None:
    """Only ``{id, name}`` of a draft's angle is kept, and only a real one."""
    if not isinstance(value, dict):
        return None
    name = str(value.get("name") or "").strip()
    if not name:
        return None
    return {"id": str(value.get("id") or "")[:40], "name": name[:40]}


def run_of_key(dedupe_key: str | None) -> str | None:
    """``auto:<run>:<version>`` → the run id (the old auto-ingest key)."""
    parts = (dedupe_key or "").split(":")
    if len(parts) == 3 and parts[0] == "auto" and re.fullmatch(ID_PATTERN, parts[1]):
        return parts[1]
    return None


def talking_used(
    session: Session, workspace: WorkspaceContext, entry_ids: list[str]
) -> set[str]:
    """Entries a (not deleted) talking work item of this user points at."""
    if not entry_ids:
        return set()
    rows = session.scalars(
        select(VideoWorkItemRecord.script_document_id)
        .where(
            VideoWorkItemRecord.workspace_id == workspace.workspace_id,
            VideoWorkItemRecord.owner_user_id == workspace.principal.user_id,
            VideoWorkItemRecord.script_document_id.in_(entry_ids),
            VideoWorkItemRecord.deleted_at.is_(None),
        )
        .distinct()
    ).all()
    return {r for r in rows if r}


def responses(
    session: Session, workspace: WorkspaceContext, rows: Any
) -> list[LibraryEntry]:
    rows = list(rows)
    used = talking_used(session, workspace, [row.id for row in rows])
    return [entry_response(row, row.id in used) for row in rows]


def entry_response(row: VideoScriptLibraryEntry, used: bool = False) -> LibraryEntry:
    chars = spoken_chars(row.script)
    angle = clean_angle(row.angle)
    return LibraryEntry(
        id=row.id,
        created_at=aware(row.created_at),
        updated_at=aware(row.updated_at),
        source=row.source,  # type: ignore[arg-type]
        platform=row.platform if row.platform in {"douyin", "xiaohongshu"} else "",  # type: ignore[arg-type]
        publish_title=row.publish_title,
        publish_body=row.publish_body,
        script=row.script,
        benchmark_refs=list(row.benchmark_refs or []),
        revision=row.revision,
        project_id=row.project_id,
        writing_document_id=row.writing_document_id,
        display_title=row.publish_title.strip()
        or first_sentence(row.script)
        or "未命名文案",
        script_chars=chars,
        script_seconds=max(1, round(chars / CHARS_PER_SECOND)) if chars else 0,
        run_id=row.run_id,
        angle=LibraryAngle(**angle) if angle else None,
        used_for_talking=used,
    )


def owned_query(workspace: WorkspaceContext) -> Any:
    return select(VideoScriptLibraryEntry).where(
        VideoScriptLibraryEntry.workspace_id == workspace.workspace_id,
        VideoScriptLibraryEntry.owner_user_id == workspace.principal.user_id,
    )


def own_entry(
    session: Session, workspace: WorkspaceContext, entry_id: str
) -> VideoScriptLibraryEntry:
    row = session.scalar(
        owned_query(workspace).where(
            VideoScriptLibraryEntry.id == entry_id,
            VideoScriptLibraryEntry.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApiError(404, "VIDEO_SCRIPT_LIBRARY_NOT_FOUND", "文案库里没有这条文案。")
    return row


# ---------------------------------------------------------------- ingest ----


def benchmark_refs(session: Session, reference_id: str | None) -> list[dict[str, Any]]:
    if not reference_id:
        return []
    ref = session.get(VideoWritingDocument, reference_id)
    if ref is None:
        return []
    metrics = (ref.body or {}).get("source_metrics") or {}
    return [
        {
            "reference_document_id": ref.id,
            "platform": metrics.get("platform") or "",
            "title": (metrics.get("title") or "")[:200],
            "author_name": metrics.get("author_name") or "",
            "source_url": (ref.body or {}).get("source_url") or "",
        }
    ]


def insert_once(
    session: Session,
    workspace: WorkspaceContext,
    row: VideoScriptLibraryEntry,
    *lookups: Any,
) -> VideoScriptLibraryEntry:
    """Insert, or return the entry a concurrent save already made."""

    def existing() -> VideoScriptLibraryEntry | None:
        for condition in lookups:
            found = session.scalar(owned_query(workspace).where(condition))
            if found is not None:
                return found
        return None

    found = existing()
    if found is not None:
        return found
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        found = existing()
        if found is None:
            raise
        return found
    return row


def ingest_draft(
    session: Session,
    workspace: WorkspaceContext,
    document: VideoWritingDocument,
    *,
    source: Source,
    dedupe_key: str,
    platform: str,
    run_id: str | None = None,
    angle: Any = None,
) -> VideoScriptLibraryEntry:
    """A saved draft document becomes one library entry, exactly once."""
    body = document.body or {}
    draft = body.get("draft") or {}
    row = VideoScriptLibraryEntry(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        source=source,
        platform=platform if platform in {"douyin", "xiaohongshu"} else "",
        publish_title=str(draft.get("publish_title") or "")[:80],
        publish_body=str(draft.get("publish_body") or "")[:2000],
        script=str(body.get("text") or ""),
        benchmark_refs=benchmark_refs(session, document.reference_document_id),
        dedupe_key=dedupe_key[:160],
        project_id=document.project_id,
        writing_document_id=document.id,
        run_id=run_id or run_of_key(dedupe_key),
        angle=clean_angle(angle),
        revision=1,
        history=[],
    )
    return insert_once(
        session,
        workspace,
        row,
        VideoScriptLibraryEntry.writing_document_id == document.id,
        VideoScriptLibraryEntry.dedupe_key == row.dedupe_key,
    )


def snapshot(row: VideoScriptLibraryEntry) -> dict[str, Any]:
    return {
        "revision": row.revision,
        "publish_title": row.publish_title,
        "publish_body": row.publish_body,
        "script": row.script,
        "platform": row.platform,
        "writing_document_id": row.writing_document_id,
        "saved_at": aware(row.updated_at).isoformat(),
    }


def apply_change(
    row: VideoScriptLibraryEntry,
    *,
    publish_title: str,
    publish_body: str,
    script: str,
    platform: str | None = None,
    writing_document_id: str | None = None,
) -> bool:
    changed = (
        row.publish_title != publish_title
        or row.publish_body != publish_body
        or row.script != script
        or (platform is not None and row.platform != platform)
        or (
            writing_document_id is not None
            and row.writing_document_id != writing_document_id
        )
    )
    if not changed:
        return False
    row.history = [*(row.history or []), snapshot(row)][-HISTORY_KEPT:]
    row.publish_title, row.publish_body, row.script = (
        publish_title,
        publish_body,
        script,
    )
    if platform is not None:
        row.platform = platform
    if writing_document_id is not None:
        row.writing_document_id = writing_document_id
    row.revision += 1
    row.updated_at = utc_now()
    return True


def follow_revision(
    session: Session,
    workspace: WorkspaceContext,
    parent_id: str,
    document: VideoWritingDocument,
) -> VideoScriptLibraryEntry | None:
    """A revised draft (逐句修改) is a new version of the entry of its parent."""
    row = session.scalar(
        owned_query(workspace).where(
            VideoScriptLibraryEntry.writing_document_id == parent_id,
            VideoScriptLibraryEntry.deleted_at.is_(None),
        )
    )
    if row is None:
        return None
    draft = (document.body or {}).get("draft") or {}
    apply_change(
        row,
        publish_title=str(draft.get("publish_title") or row.publish_title)[:80],
        publish_body=str(draft.get("publish_body") or row.publish_body)[:2000],
        script=str((document.body or {}).get("text") or row.script),
        writing_document_id=document.id,
    )
    session.commit()
    return row


def sync_legacy(session: Session, workspace: WorkspaceContext) -> None:
    """Mirror old library snapshots; never takes the library page down.

    Two first reads at once both try to mirror the same snapshot: the unique
    ``legacy_version_id`` makes one of them lose, and ``insert_once`` returns
    the winner's row. Any other failure only skips mirroring this time.
    """
    try:
        mirror_legacy(session, workspace)
    except Exception:  # noqa: BLE001 - the list still answers without mirroring
        session.rollback()
        log.warning("script library: legacy mirroring skipped", exc_info=True)


def mirror_legacy(session: Session, workspace: WorkspaceContext) -> None:
    mirrored = select(VideoScriptLibraryEntry.legacy_version_id).where(
        VideoScriptLibraryEntry.legacy_version_id.is_not(None),
        VideoScriptLibraryEntry.workspace_id == workspace.workspace_id,
        VideoScriptLibraryEntry.owner_user_id == workspace.principal.user_id,
    )
    versions = session.scalars(
        select(VideoScriptVersionRecord)
        .join(VideoProjectRecord)
        .where(
            *scope(workspace),
            VideoScriptVersionRecord.kind == "library",
            VideoScriptVersionRecord.id.not_in(mirrored),
        )
        .order_by(VideoScriptVersionRecord.created_at)
        .limit(500)
    ).all()
    for version in versions:
        draft = (version.snapshot or {}).get("draft") or {}
        text = str(draft.get("text") or "").strip()
        if not text:
            continue
        name = str(draft.get("name") or "").strip()
        row = VideoScriptLibraryEntry(
            id=str(uuid4()),
            workspace_id=workspace.workspace_id,
            owner_user_id=workspace.principal.user_id,
            source="manual",
            platform="",
            publish_title="" if name in {"", DEFAULT_NAME} else name[:80],
            publish_body="",
            script=text,
            benchmark_refs=[],
            dedupe_key=f"legacy:{version.id}",
            project_id=version.project_id,
            legacy_version_id=version.id,
            revision=1,
            history=[],
            created_at=version.created_at,
            updated_at=version.created_at,
        )
        insert_once(
            session,
            workspace,
            row,
            VideoScriptLibraryEntry.legacy_version_id == version.id,
        )


# ---------------------------------------------------------------- routes ----


def parse_ids(raw: str) -> list[str]:
    ids: list[str] = []
    for piece in raw.split(","):
        piece = piece.strip()
        if piece and piece not in ids:
            ids.append(piece)
    if len(ids) > MAX_IDS:
        raise ApiError(
            422, "VIDEO_SCRIPT_LIBRARY_TOO_MANY", f"一次最多取 {MAX_IDS} 条文案。"
        )
    for ident in ids:
        if not re.fullmatch(ID_PATTERN, ident):
            raise ApiError(422, "VIDEO_SCRIPT_LIBRARY_BAD_ID", "文案编号不正确。")
    return ids


@router.get("/script-library", response_model=LibraryPage)
def list_entries(
    workspace: VideoWorkspace,
    session: SessionDependency,
    ids: str = Query("", max_length=2100),
    # Entries made from these writing documents (result pages find theirs).
    documents: str = Query("", max_length=2100),
    q: str = Query("", max_length=100),
    platform: Literal["", "douyin", "xiaohongshu"] = "",
    # 按生成批次：某次 run 的 id，或 "none" = 不来自任何一次生成（「更早的」）。
    run_id: str = Query("", max_length=40, pattern=r"^[0-9A-Za-z-]*$"),
    source: Literal["", "auto_writing", "manual", "imported"] = "",
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> LibraryPage:
    sync_legacy(session, workspace)
    live = owned_query(workspace).where(VideoScriptLibraryEntry.deleted_at.is_(None))
    wanted = parse_ids(ids)
    if wanted:
        by_id = {
            row.id: row
            for row in session.scalars(
                live.where(VideoScriptLibraryEntry.id.in_(wanted))
            ).all()
        }
        items = responses(session, workspace, [by_id[i] for i in wanted if i in by_id])
        return LibraryPage(
            items=items,
            total=len(items),
            limit=len(wanted),
            offset=0,
            missing_ids=[i for i in wanted if i not in by_id],
        )
    docs = parse_ids(documents)
    if docs:
        found = session.scalars(
            live.where(VideoScriptLibraryEntry.writing_document_id.in_(docs))
        ).all()
        return LibraryPage(
            items=responses(session, workspace, found),
            total=len(found),
            limit=len(docs),
            offset=0,
        )
    if q.strip():
        pattern = (
            "%"
            + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        live = live.where(
            or_(
                VideoScriptLibraryEntry.publish_title.ilike(pattern, escape="\\"),
                VideoScriptLibraryEntry.publish_body.ilike(pattern, escape="\\"),
                VideoScriptLibraryEntry.script.ilike(pattern, escape="\\"),
            )
        )
    if platform:
        live = live.where(VideoScriptLibraryEntry.platform == platform)
    if run_id == "none":
        live = live.where(VideoScriptLibraryEntry.run_id.is_(None))
    elif run_id:
        live = live.where(VideoScriptLibraryEntry.run_id == run_id)
    if source:
        live = live.where(VideoScriptLibraryEntry.source == source)
    total = session.scalar(select(func.count()).select_from(live.subquery())) or 0
    rows = session.scalars(
        live.order_by(
            VideoScriptLibraryEntry.created_at.desc(), VideoScriptLibraryEntry.id
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return LibraryPage(
        items=responses(session, workspace, rows),
        total=total,
        limit=limit,
        offset=offset,
    )


class RunGroup(StrictVideoModel):
    run_id: str | None
    created_at: datetime | None
    label: str
    count: int
    platforms: list[str]


class RunGroups(StrictVideoModel):
    groups: list[RunGroup]


def run_label(run: VideoAssistanceRecord | None) -> str:
    if run is None:
        return "爆款文案"
    result = run.result or {}
    brief = result.get("brief") if isinstance(result.get("brief"), dict) else {}
    asked = result.get("request") if isinstance(result.get("request"), dict) else {}
    for value in (
        (brief or {}).get("category"),
        (asked or {}).get("query"),
        (run.inputs or {}).get("query"),
    ):
        lines = str(value or "").strip().splitlines()
        label = lines[0].strip() if lines else ""
        if label:
            return label if len(label) <= 20 else label[:20] + "…"
    return "爆款文案"


@router.get("/script-library/runs", response_model=RunGroups)
def list_runs(workspace: VideoWorkspace, session: SessionDependency) -> RunGroups:
    """按生成批次分组：每次爆款文案一组（新的在前），没有批次的在「更早的」."""
    sync_legacy(session, workspace)
    counted = session.execute(
        select(
            VideoScriptLibraryEntry.run_id,
            VideoScriptLibraryEntry.platform,
            func.count(),
            func.min(VideoScriptLibraryEntry.created_at),
        )
        .where(
            VideoScriptLibraryEntry.workspace_id == workspace.workspace_id,
            VideoScriptLibraryEntry.owner_user_id == workspace.principal.user_id,
            VideoScriptLibraryEntry.deleted_at.is_(None),
        )
        .group_by(VideoScriptLibraryEntry.run_id, VideoScriptLibraryEntry.platform)
    ).all()
    groups: dict[str | None, dict[str, Any]] = {}
    for run_id, platform, count, first in counted:
        group = groups.setdefault(run_id, {"count": 0, "platforms": [], "first": None})
        group["count"] += int(count)
        if platform and platform not in group["platforms"]:
            group["platforms"].append(platform)
        if first is not None and (
            group["first"] is None or aware(first) < group["first"]
        ):
            group["first"] = aware(first)
    run_ids = [key for key in groups if key]
    runs: dict[str, VideoAssistanceRecord] = {}
    if run_ids:
        runs = {
            row.id: row
            for row in session.scalars(
                select(VideoAssistanceRecord).where(
                    VideoAssistanceRecord.id.in_(run_ids),
                    VideoAssistanceRecord.workspace_id == workspace.workspace_id,
                    VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
                )
            ).all()
        }
    named: list[RunGroup] = []
    for key in run_ids:
        group, run = groups[key], runs.get(key)
        when = aware(run.created_at) if run is not None else group["first"]
        named.append(
            RunGroup(
                run_id=key,
                created_at=when,
                label=run_label(run),
                count=group["count"],
                platforms=sorted(group["platforms"]),
            )
        )
    epoch = datetime.min.replace(tzinfo=UTC)
    named.sort(key=lambda g: (g.created_at or epoch, g.run_id or ""), reverse=True)
    if None in groups:
        older = groups[None]
        named.append(
            RunGroup(
                run_id=None,
                created_at=None,
                label=OLDER_LABEL,
                count=older["count"],
                platforms=sorted(older["platforms"]),
            )
        )
    return RunGroups(groups=named)


# ------------------------------------------------------------ batches ----


class BatchStore(StrictVideoModel):
    # Counted by hand (not max_length): too many is VIDEO_SCRIPT_LIBRARY_TOO_MANY.
    document_ids: list[str] = Field(min_length=1, max_length=1000)
    run_id: str | None = Field(default=None, max_length=40)


class BatchStored(StrictVideoModel):
    items: list[LibraryEntry]
    created: int
    restored: int


class BatchDelete(StrictVideoModel):
    ids: list[str] = Field(min_length=1, max_length=1000)


class BatchDeleted(StrictVideoModel):
    deleted: int
    ids: list[str]
    missing_ids: list[str]


def batch_ids(raw: list[str]) -> list[str]:
    ids = list(dict.fromkeys(piece.strip() for piece in raw if piece.strip()))
    if not ids:
        raise ApiError(422, "VIDEO_SCRIPT_LIBRARY_BAD_ID", "文案编号不正确。")
    if len(ids) > MAX_BATCH:
        raise ApiError(
            422, "VIDEO_SCRIPT_LIBRARY_TOO_MANY", f"一次最多 {MAX_BATCH} 条文案。"
        )
    if any(not re.fullmatch(ID_PATTERN, ident) for ident in ids):
        raise ApiError(422, "VIDEO_SCRIPT_LIBRARY_BAD_ID", "文案编号不正确。")
    return ids


def run_drafts(
    session: Session,
    workspace: WorkspaceContext,
    documents: list[VideoWritingDocument],
    run_id: str | None,
) -> dict[str, tuple[str, dict[str, Any]]]:
    """document id → (run id, that run's draft entry) for auto-writing drafts.

    With ``run_id`` only that run is read; otherwise the auto-writing runs of
    the projects the documents belong to (newest first). A draft the checks
    dropped but the user keeps anyway is found by ``dropped_document_id``.
    """
    query = select(VideoAssistanceRecord).where(
        VideoAssistanceRecord.workspace_id == workspace.workspace_id,
        VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
        VideoAssistanceRecord.kind == AUTO_KIND,
    )
    if run_id:
        query = query.where(VideoAssistanceRecord.id == run_id)
    else:
        projects = sorted({doc.project_id for doc in documents})
        query = query.where(VideoAssistanceRecord.project_id.in_(projects))
    found: dict[str, tuple[str, dict[str, Any]]] = {}
    runs = session.scalars(
        query.order_by(VideoAssistanceRecord.created_at.desc()).limit(50)
    ).all()
    for run in runs:
        for draft in (run.result or {}).get("drafts") or []:
            if not isinstance(draft, dict) or not draft.get("key"):
                continue
            for field in ("document_id", "dropped_document_id"):
                doc_id = draft.get(field)
                if doc_id and str(doc_id) not in found:
                    found[str(doc_id)] = (run.id, draft)
    return found


def draft_platform(session: Session, document: VideoWritingDocument) -> str:
    if document.assistance_task_id:
        task = session.get(VideoAssistanceRecord, document.assistance_task_id)
        if task is not None:
            return str((task.inputs or {}).get("publish_platform") or "")
    return ""


@router.post("/script-library/batch", response_model=BatchStored)
def store_batch(
    body: BatchStore, workspace: VideoWorkspace, session: SessionDependency
) -> BatchStored:
    """「存入文案库」：勾选的几份文稿一次存入；同一文稿永远只有一条."""
    require_workspace_write(workspace)
    ids = batch_ids(body.document_ids)
    if body.run_id is not None and not re.fullmatch(ID_PATTERN, body.run_id):
        raise ApiError(422, "VIDEO_SCRIPT_LIBRARY_BAD_ID", "文案编号不正确。")
    rows = {
        doc.id: doc
        for doc in session.scalars(
            select(VideoWritingDocument).where(
                VideoWritingDocument.id.in_(ids),
                VideoWritingDocument.workspace_id == workspace.workspace_id,
                VideoWritingDocument.owner_user_id == workspace.principal.user_id,
                VideoWritingDocument.kind == "draft",
            )
        ).all()
    }
    missing = [i for i in ids if i not in rows]
    if missing:
        raise ApiError(
            404,
            "VIDEO_WRITING_DOCUMENT_NOT_FOUND",
            "有几份文稿没有找到，这次没有存入。",
            details={"missing_ids": missing},
        )
    documents = [rows[i] for i in ids]
    from_runs = run_drafts(session, workspace, documents, body.run_id)
    created = restored = 0
    saved: list[VideoScriptLibraryEntry] = []
    for document in documents:
        before = session.scalar(
            owned_query(workspace).where(
                VideoScriptLibraryEntry.writing_document_id == document.id
            )
        )
        run_id, draft = from_runs.get(document.id, (None, {}))
        key = f"auto:{run_id}:{draft['key']}" if run_id else f"document:{document.id}"
        row = ingest_draft(
            session,
            workspace,
            document,
            source="auto_writing" if run_id else "manual",
            dedupe_key=key,
            platform=str(draft.get("platform") or draft_platform(session, document)),
            run_id=run_id,
            angle=draft.get("angle"),
        )
        changed = False
        if before is None and row.writing_document_id == document.id:
            created += 1
        if row.deleted_at is not None:  # removed earlier, stored again on purpose
            row.deleted_at = None
            row.updated_at = utc_now()
            restored += 1
            changed = True
        angle = clean_angle(draft.get("angle"))
        if run_id and row.run_id is None:
            row.run_id, changed = run_id, True
        if run_id and row.angle is None and angle:
            row.angle, changed = angle, True
        if changed:
            session.commit()
        saved.append(row)
    return BatchStored(
        items=responses(session, workspace, saved), created=created, restored=restored
    )


@router.post("/script-library/batch-delete", response_model=BatchDeleted)
def delete_batch(
    body: BatchDelete, workspace: VideoWorkspace, session: SessionDependency
) -> BatchDeleted:
    """文案库多选删除：只删自己的，一次请求；别人的、没有的、已删的忽略."""
    require_workspace_write(workspace)
    ids = batch_ids(body.ids)
    mine = set(
        session.scalars(
            select(VideoScriptLibraryEntry.id).where(
                VideoScriptLibraryEntry.workspace_id == workspace.workspace_id,
                VideoScriptLibraryEntry.owner_user_id == workspace.principal.user_id,
                VideoScriptLibraryEntry.id.in_(ids),
                VideoScriptLibraryEntry.deleted_at.is_(None),
            )
        ).all()
    )
    if mine:
        now = utc_now()
        session.execute(
            update(VideoScriptLibraryEntry)
            .where(
                VideoScriptLibraryEntry.workspace_id == workspace.workspace_id,
                VideoScriptLibraryEntry.owner_user_id == workspace.principal.user_id,
                VideoScriptLibraryEntry.id.in_(mine),
                VideoScriptLibraryEntry.deleted_at.is_(None),
            )
            .values(deleted_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        session.commit()
    done = [i for i in ids if i in mine]
    return BatchDeleted(
        deleted=len(done), ids=done, missing_ids=[i for i in ids if i not in mine]
    )


@router.get("/script-library/{entry_id}", response_model=LibraryEntry)
def get_entry(
    entry_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> LibraryEntry:
    row = own_entry(session, workspace, entry_id)
    return entry_response(row, bool(talking_used(session, workspace, [row.id])))


@router.post("/script-library", response_model=LibraryEntry)
def create_entry(
    body: LibraryCreate, workspace: VideoWorkspace, session: SessionDependency
) -> LibraryEntry:
    require_workspace_write(workspace)
    document = None
    if body.writing_document_id is not None:
        document = session.get(VideoWritingDocument, str(body.writing_document_id))
        if (
            document is None
            or document.workspace_id != workspace.workspace_id
            or document.owner_user_id != workspace.principal.user_id
            or document.kind != "draft"
        ):
            raise ApiError(
                404, "VIDEO_WRITING_DOCUMENT_NOT_FOUND", "未找到这份文稿资料。"
            )
    row = VideoScriptLibraryEntry(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        source=body.source if document is not None else "manual",
        platform=body.platform,
        publish_title=body.publish_title.strip(),
        publish_body=body.publish_body.strip(),
        script=body.script,
        benchmark_refs=benchmark_refs(
            session, document.reference_document_id if document else None
        ),
        dedupe_key=(
            f"document:{document.id}"
            if document is not None
            else f"request:{body.request_id}"
        ),
        project_id=document.project_id if document else None,
        writing_document_id=document.id if document else None,
        revision=1,
        history=[],
    )
    lookups = [VideoScriptLibraryEntry.dedupe_key == row.dedupe_key]
    if document is not None:
        lookups.insert(0, VideoScriptLibraryEntry.writing_document_id == document.id)
    saved = insert_once(session, workspace, row, *lookups)
    if saved.deleted_at is not None:  # removed earlier, stored again on purpose
        saved.deleted_at = None
        saved.updated_at = utc_now()
        session.commit()
    return entry_response(saved)


@router.put("/script-library/{entry_id}", response_model=LibraryEntry)
def update_entry(
    entry_id: str,
    body: LibraryUpdate,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> LibraryEntry:
    require_workspace_write(workspace)
    row = own_entry(session, workspace, entry_id)
    change = {
        "publish_title": body.publish_title.strip(),
        "publish_body": body.publish_body.strip(),
        "script": body.script,
        "platform": body.platform or row.platform,
    }
    unchanged = all(getattr(row, key) == value for key, value in change.items())
    if unchanged and body.expected_revision in {row.revision, row.revision - 1}:
        return entry_response(row)  # a repeated save of what is already stored
    if row.revision != body.expected_revision:
        raise ApiError(
            409,
            "VIDEO_SCRIPT_LIBRARY_CHANGED",
            "这条文案已在别处改过，请刷新后再改。",
        )
    apply_change(row, **change)
    session.commit()
    return entry_response(row)


@router.delete("/script-library/{entry_id}")
def delete_entry(
    entry_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> dict[str, Any]:
    require_workspace_write(workspace)
    row = own_entry(session, workspace, entry_id)
    row.deleted_at = utc_now()
    session.commit()
    return {"id": row.id, "deleted": True}


# ------------------------------------------------- 补写标题和正文（旧文案）----

FILL_KIND = "publish_fill"
FILL_ACTION = "writing_publish_fill"


class FillRequest(StrictVideoModel):
    request_id: UUID
    platform: Platform


class FillStatus(StrictVideoModel):
    task_id: str
    status: str
    error_code: str | None
    message: str
    entry: LibraryEntry | None


def fill_status(
    session: Session, workspace: WorkspaceContext, task: VideoAssistanceRecord
) -> FillStatus:
    entry = session.scalar(
        owned_query(workspace).where(
            VideoScriptLibraryEntry.id == task.inputs.get("entry_id"),
            VideoScriptLibraryEntry.deleted_at.is_(None),
        )
    )
    return FillStatus(
        task_id=task.id,
        status=task.status,
        error_code=task.error_code,
        message=str((task.result or {}).get("message") or ""),
        entry=entry_response(entry) if entry else None,
    )


def attach_project(
    session: Session, workspace: WorkspaceContext, row: VideoScriptLibraryEntry
) -> str:
    """A task belongs to a project; a manual entry without one gets its own."""
    content = VideoProjectContent.model_validate(
        {
            "draft": {
                "name": (row.publish_title or "文案库文案")[:80],
                "text": row.script[:3000],
            }
        }
    )
    project = VideoProjectRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        revision=1,
        content=content.model_dump(mode="json"),
    )
    session.add(project)
    session.flush()
    row.project_id = project.id
    return project.id


def run_fill(factory: Any, task_id: str, service: Any) -> None:
    """Write the title and body; the entry gets them as a new revision."""
    from .video_writing_provider import plan_publish_fill

    with factory() as session:
        task = session.get(VideoAssistanceRecord, task_id)
        if task is None or task.status != "running":
            return
        inputs = dict(task.inputs)
    try:
        result, receipt = plan_publish_fill(
            service, inputs["script"], inputs["platform"]
        )
    except Exception:  # noqa: BLE001 - provider down: failed, not charged
        log.warning("script library: publish fill call failed", exc_info=True)
        result, receipt = {"validation_error": "VIDEO_WRITING_PROVIDER_FAILED"}, {}
    with factory() as session:
        task = session.get(VideoAssistanceRecord, task_id)
        assert task is not None
        task.receipt = receipt
        entry = session.get(VideoScriptLibraryEntry, inputs["entry_id"])
        if result.get("validation_error") or entry is None or entry.deleted_at:
            task.status, task.stage = "failed", "done"
            task.error_code = (
                "VIDEO_SCRIPT_LIBRARY_NOT_FOUND"
                if entry is None or (entry and entry.deleted_at)
                else str(result.get("validation_error"))
            )
            task.result = {
                **{k: v for k, v in result.items() if k != "validation_error"},
                "message": "这次没写好，没有扣积分，可以再试一次。",
            }
        else:
            apply_change(
                entry,
                publish_title=str(result["publish_title"])[:80],
                publish_body=str(result["publish_body"])[:2000],
                script=entry.script,
                platform=inputs["platform"],
            )
            task.status, task.stage = "completed", "done"
            task.result = {
                "entry_id": entry.id,
                "revision": entry.revision,
                "publish_title": entry.publish_title,
                "publish_body": entry.publish_body,
                "warnings": result.get("warnings") or [],
                "message": "",
            }
        task.updated_at = utc_now()
        session.commit()


@router.post("/script-library/{entry_id}/publish-fill", response_model=FillStatus)
def start_fill(
    entry_id: str,
    body: FillRequest,
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> FillStatus:
    require_workspace_write(workspace)
    settings = request.app.state.settings
    existing = session.scalar(
        select(VideoAssistanceRecord).where(
            VideoAssistanceRecord.workspace_id == workspace.workspace_id,
            VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
            VideoAssistanceRecord.request_id == str(body.request_id),
        )
    )
    if existing:
        if existing.kind != FILL_KIND or existing.inputs.get("entry_id") != entry_id:
            raise ApiError(409, "VIDEO_REQUEST_REUSED", "此请求已提交过其他内容。")
        return fill_status(session, workspace, existing)
    if not settings.video_script_planning_enabled:
        raise ApiError(503, "VIDEO_ASSISTANCE_DISABLED", "写稿服务尚未开放。")
    row = own_entry(session, workspace, entry_id)
    running = session.scalar(
        select(VideoAssistanceRecord).where(
            VideoAssistanceRecord.workspace_id == workspace.workspace_id,
            VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
            VideoAssistanceRecord.kind == FILL_KIND,
            VideoAssistanceRecord.status == "running",
            VideoAssistanceRecord.inputs["entry_id"].as_string() == row.id,
        )
    )
    if running:
        return fill_status(session, workspace, running)
    project_id = row.project_id or attach_project(session, workspace, row)
    task = VideoAssistanceRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=project_id,
        request_id=str(body.request_id),
        request_hash=str(body.request_id),
        kind=FILL_KIND,
        status="running",
        stage="fill",
        inputs={
            "revision": row.revision,
            "entry_id": row.id,
            "platform": body.platform,
            "script": row.script,
        },
        result={},
    )
    session.add(task)
    try:
        video_credits.hold(
            session,
            settings,
            workspace.workspace_id,
            FILL_ACTION,
            "video_assistance",
            task.id,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ApiError(
            409, "VIDEO_REQUEST_REUSED", "补写请求发生冲突，请重试。"
        ) from None
    factory = request.app.state.session_factory
    background.add_task(run_fill, factory, task.id, provider(request))
    background.add_task(
        video_credits.settle_after, factory, "video_assistance", task.id
    )
    return fill_status(session, workspace, task)


@router.get(
    "/script-library/{entry_id}/publish-fill/{task_id}", response_model=FillStatus
)
def get_fill(
    entry_id: str, task_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> FillStatus:
    task = session.get(VideoAssistanceRecord, task_id)
    if (
        task is None
        or task.kind != FILL_KIND
        or task.workspace_id != workspace.workspace_id
        or task.owner_user_id != workspace.principal.user_id
        or task.inputs.get("entry_id") != entry_id
    ):
        raise ApiError(404, "VIDEO_SCRIPT_LIBRARY_NOT_FOUND", "没有找到这次补写。")
    return fill_status(session, workspace, task)
