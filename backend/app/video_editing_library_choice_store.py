"""Take one consistent, owner-scoped selection snapshot for planning and rendering."""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .motion_library import MOTION_SHA256
from .video_editing_catalog import choice_snapshot_hash
from .video_editing_task_models import EditingLibraryNoteRecord


def stored_choice_snapshot(
    session: Session, workspace_id: str, owner_user_id: str, project_id: str
) -> dict[str, Any]:
    scope = (
        EditingLibraryNoteRecord.workspace_id == workspace_id,
        EditingLibraryNoteRecord.owner_user_id == owner_user_id,
        EditingLibraryNoteRecord.project_id == project_id,
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
        "project_id": project_id,
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
