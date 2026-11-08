"""Scoped immutable selection memos, with explicit parent/version concurrency."""

from datetime import UTC
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .auth import SessionDependency, require_workspace_write
from .errors import ApiError
from .motion_library import MOTION_SHA256, read_json, sha256
from .video_editing_catalog import asset_label, choice_snapshot_hash
from .video_editing_contracts import (
    EditingLibraryNoteCreate,
    EditingLibraryNoteResponse,
    EditingLibraryNotesResponse,
    LibraryChoiceSnapshot,
)
from .video_editing_task_models import EditingLibraryNoteRecord
from .video_editing_task_routes import enabled, own_project
from .video_studio_routes import VideoWorkspace, digest

router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}/projects/{project_id}",
    tags=["video-editing-library-notes"],
)


@router.get("/editing-library-choice-snapshot", response_model=LibraryChoiceSnapshot)
def planning_choice_snapshot(
    project_id: UUID,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    own_project(session, workspace, str(project_id))
    scope = (
        EditingLibraryNoteRecord.workspace_id == workspace.workspace_id,
        EditingLibraryNoteRecord.owner_user_id == workspace.principal.user_id,
        EditingLibraryNoteRecord.project_id == str(project_id),
        EditingLibraryNoteRecord.library_release == MOTION_SHA256,
    )
    ranked = (
        select(
            EditingLibraryNoteRecord.id,
            func.row_number()
            .over(
                partition_by=(
                    EditingLibraryNoteRecord.target_kind,
                    EditingLibraryNoteRecord.target_id,
                ),
                order_by=EditingLibraryNoteRecord.sequence.desc(),
            )
            .label("position"),
        )
        .where(*scope)
        .subquery()
    )
    # One statement sees a consistent set of current versions, even if another
    # browser writes notes during paginated UI reads.
    rows = session.scalars(
        select(EditingLibraryNoteRecord)
        .join(
            ranked,
            ranked.c.id == EditingLibraryNoteRecord.id,
        )
        .where(*scope, ranked.c.position == 1)
        .order_by(
            EditingLibraryNoteRecord.target_kind,
            EditingLibraryNoteRecord.target_id,
        )
    )
    data = {
        "schema_version": "tengli.library-choice-snapshot/1",
        "scope": "project_selection_memo",
        "project_id": str(project_id),
        "library_release": MOTION_SHA256,
        "notes": [
            {
                "note_id": r.id,
                "target_kind": r.target_kind,
                "target_id": r.target_id,
                "target_name": r.details["target_name"],
                "sequence": r.sequence,
                "choice": r.choice,
                "reason": r.reason,
            }
            for r in rows
        ],
    }
    return {**data, "sha256": choice_snapshot_hash(data)}


def response(row: EditingLibraryNoteRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "library_release": row.library_release,
        "target_kind": row.target_kind,
        "target_id": row.target_id,
        "target_name": row.details["target_name"],
        "choice": row.choice,
        "reason": row.reason,
        "sequence": row.sequence,
        "parent_note_id": row.parent_note_id,
        "scope": "project_selection_memo",
        "created_at": row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
    }


@router.post("/editing-library-notes", response_model=EditingLibraryNoteResponse)
def save_note(
    project_id: UUID,
    body: EditingLibraryNoteCreate,
    request: Request,
    workspace: VideoWorkspace,
    session: SessionDependency,
) -> dict[str, Any]:
    require_workspace_write(workspace)
    package = enabled(request).video_editing_library_dir
    own_project(session, workspace, str(project_id))
    fingerprint = digest(
        {
            "project_id": str(project_id),
            "release": MOTION_SHA256,
            **body.model_dump(mode="json"),
        }
    )
    scope = (
        EditingLibraryNoteRecord.workspace_id == workspace.workspace_id,
        EditingLibraryNoteRecord.owner_user_id == workspace.principal.user_id,
    )
    previous = session.scalar(
        select(EditingLibraryNoteRecord).where(
            *scope,
            EditingLibraryNoteRecord.request_id == str(body.request_id),
        )
    )
    if previous:
        if previous.request_hash != fingerprint:
            raise ApiError(
                409,
                "EDITING_LIBRARY_NOTE_REQUEST_REUSED",
                "请求编号已用于其他选组记录。",
            )
        return response(previous)
    if body.target_kind == "group":
        rows = read_json(package / "catalog/groups.json")["groups"]
    elif body.target_kind == "bundled_asset":
        rows = read_json(package / "asset-manifest.json")["assets"]
    else:
        rows = read_json(package / "catalog/external-resources.json")["resources"]
    target = next((r for r in rows if r["id"] == body.target_id), None)
    if target is None:
        raise ApiError(404, "EDITING_LIBRARY_TARGET_NOT_FOUND", "未找到此原库条目。")
    latest = session.scalar(
        select(EditingLibraryNoteRecord)
        .where(
            *scope,
            EditingLibraryNoteRecord.project_id == str(project_id),
            EditingLibraryNoteRecord.library_release == MOTION_SHA256,
            EditingLibraryNoteRecord.target_kind == body.target_kind,
            EditingLibraryNoteRecord.target_id == body.target_id,
        )
        .order_by(EditingLibraryNoteRecord.sequence.desc())
        .limit(1)
    )
    if (latest.id if latest else None) != (
        str(body.parent_note_id) if body.parent_note_id else None
    ):
        raise ApiError(
            409,
            "EDITING_LIBRARY_NOTE_STALE",
            "这个条目的选组记录已更新，请刷新后修改。",
        )
    row = EditingLibraryNoteRecord(
        id=str(uuid4()),
        workspace_id=workspace.workspace_id,
        owner_user_id=workspace.principal.user_id,
        project_id=str(project_id),
        library_release=MOTION_SHA256,
        request_id=str(body.request_id),
        request_hash=fingerprint,
        target_kind=body.target_kind,
        target_id=body.target_id,
        sequence=(latest.sequence + 1) if latest else 1,
        choice=body.choice,
        reason=body.reason,
        parent_note_id=latest.id if latest else None,
        details={
            "target_name": target.get("name")
            if body.target_kind == "group"
            else asset_label(target),
            "catalog_sha256": sha256(package / "catalog/groups.json"),
            "render_approval_inferred": False,
            "audition_approval_inferred": False,
        },
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        replay = session.scalar(
            select(EditingLibraryNoteRecord).where(
                *scope,
                EditingLibraryNoteRecord.request_id == str(body.request_id),
            )
        )
        if replay and replay.request_hash == fingerprint:
            return response(replay)
        raise ApiError(
            409, "EDITING_LIBRARY_NOTE_CONFLICT", "选组记录保存冲突，请刷新后重试。"
        ) from None
    return response(row)


@router.get("/editing-library-notes", response_model=EditingLibraryNotesResponse)
def list_notes(
    project_id: UUID,
    workspace: VideoWorkspace,
    session: SessionDependency,
    latest_only: bool = True,
    target_kind: Literal["group", "bundled_asset", "external_resource"] | None = None,
    target_id: str | None = Query(default=None, max_length=160),
    release: str = Query(default=MOTION_SHA256, pattern="^[a-f0-9]{64}$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict[str, Any]:
    own_project(session, workspace, str(project_id))
    scope = [
        EditingLibraryNoteRecord.workspace_id == workspace.workspace_id,
        EditingLibraryNoteRecord.owner_user_id == workspace.principal.user_id,
        EditingLibraryNoteRecord.project_id == str(project_id),
        EditingLibraryNoteRecord.library_release == release,
    ]
    if target_kind is not None:
        scope.append(EditingLibraryNoteRecord.target_kind == target_kind)
    if target_id is not None:
        scope.append(EditingLibraryNoteRecord.target_id == target_id)
    query = select(EditingLibraryNoteRecord).where(*scope)
    if latest_only:
        ranked = (
            select(
                EditingLibraryNoteRecord.id,
                func.row_number()
                .over(
                    partition_by=(
                        EditingLibraryNoteRecord.target_kind,
                        EditingLibraryNoteRecord.target_id,
                    ),
                    order_by=EditingLibraryNoteRecord.sequence.desc(),
                )
                .label("position"),
            )
            .where(*scope)
            .subquery()
        )
        query = query.join(ranked, ranked.c.id == EditingLibraryNoteRecord.id).where(
            ranked.c.position == 1
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(
            EditingLibraryNoteRecord.created_at.desc(),
            EditingLibraryNoteRecord.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    return {
        "items": [response(r) for r in rows],
        "total": total,
        "next_offset": offset + limit if offset + limit < total else None,
    }
