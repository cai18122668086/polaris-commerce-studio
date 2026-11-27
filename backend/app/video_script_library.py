"""文案库（契约 C1）：每条 = 发布标题 + 发布正文 + 口播稿。

* 写稿通过检查、保存成文稿的那一刻自动入库（``ingest_draft``），幂等键是
  「运行 id + 版本序号」，同一份文稿无论从哪条路保存也只入库一次。
* 用户改了再存是同一条的新版本（``revision`` + ``history``），不是新条目。
* 老的文案库（``video_script_versions`` 里 kind=library 的快照）在主人第一次
  打开文案库时镜像进来（``legacy_version_id``），没有标题和正文也能正常显示。
* 列表一次可取多条、可按 id 批量取（给口播页 ``?scripts=id1,id2``）。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import Field, StringConstraints
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .errors import ApiError
from .models import utc_now
from .video_studio_access import require_video_studio_access
from .video_studio_models import VideoProjectRecord, VideoScriptVersionRecord
from .video_studio_routes import VideoWorkspace, scope
from .video_studio_schemas import StrictVideoModel
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


class LibraryUpdate(LibraryWrite):
    expected_revision: int = Field(ge=1)


def aware(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def entry_response(row: VideoScriptLibraryEntry) -> LibraryEntry:
    chars = spoken_chars(row.script)
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
        if not re.fullmatch(r"[0-9A-Za-z-]{1,40}", ident):
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
        items = [entry_response(by_id[i]) for i in wanted if i in by_id]
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
            items=[entry_response(row) for row in found],
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
    total = session.scalar(select(func.count()).select_from(live.subquery())) or 0
    rows = session.scalars(
        live.order_by(
            VideoScriptLibraryEntry.created_at.desc(), VideoScriptLibraryEntry.id
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return LibraryPage(
        items=[entry_response(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/script-library/{entry_id}", response_model=LibraryEntry)
def get_entry(
    entry_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> LibraryEntry:
    return entry_response(own_entry(session, workspace, entry_id))


@router.post("/script-library", response_model=LibraryEntry)
def create_entry(
    body: LibraryCreate, workspace: VideoWorkspace, session: SessionDependency
) -> LibraryEntry:
    require_workspace_write(workspace)
    row = VideoScriptLibraryEntry(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        source="manual",
        platform=body.platform,
        publish_title=body.publish_title.strip(),
        publish_body=body.publish_body.strip(),
        script=body.script,
        benchmark_refs=[],
        dedupe_key=f"request:{body.request_id}",
        revision=1,
        history=[],
    )
    return entry_response(
        insert_once(
            session,
            workspace,
            row,
            VideoScriptLibraryEntry.dedupe_key == row.dedupe_key,
        )
    )


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
