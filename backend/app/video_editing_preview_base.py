"""Resolve a verified earlier preview of the same source and frozen plan."""

import re
from pathlib import Path

from sqlalchemy.orm import Session

from .config import Settings
from .motion_library import MOTION_SHA256, sha256
from .video_editing_delivery_checkpoint import verified_delivery_file
from .video_editing_task_models import (
    EditingArtifactRecord,
    EditingSourceRecord,
    EditingTaskRecord,
)


def preview_base_attempt(
    session: Session, settings: Settings, source: EditingSourceRecord, options: dict
) -> Path | None:
    base = options.get("preview_base")
    if not base:
        return None
    parent = session.get(EditingTaskRecord, base["task_id"])
    if (
        not parent
        or (
            parent.workspace_id,
            parent.owner_user_id,
            parent.project_id,
            parent.source_id,
        )
        != (source.workspace_id, source.owner_user_id, source.project_id, source.id)
        or parent.library_release != MOTION_SHA256
        or parent.status not in {"awaiting_review", "completed"}
        or parent.options.get("delivery") != "preview_first"
        or parent.options.get("native_plan_id") != options["native_plan_id"]
    ):
        return None
    preview = session.get(EditingArtifactRecord, base["preview_artifact_id"])
    if (
        not preview
        or (preview.task_id, preview.role, preview.sha256)
        != (parent.id, "preview", base["preview_sha256"])
        or preview.validation.get("decoded") is not True
    ):
        return None
    task_root = (settings.video_editing_tasks_dir / parent.id).resolve()
    try:
        path = Path(preview.path).resolve()
        attempt = path.parent.parent
        if (
            attempt.parent != task_root
            or not re.fullmatch(r"[0-9a-f]{8}", attempt.name)
            or path != attempt / "outputs/preview.mp4"
            or path.stat().st_size != preview.bytes
            or sha256(path) != preview.sha256
        ):
            return None
        if repaired := parent.checkpoint.get("recovered_preview"):
            master = session.get(EditingArtifactRecord, repaired["master_id"])
            if (
                not master
                or master.task_id != parent.id
                or master.role not in {"staged_final", "final"}
                or master.sha256 != preview.validation.get("native_render_sha256")
                or master.validation.get("decoded") is not True
                or not verified_delivery_file(master, task_root)
            ):
                return None
            master_path = Path(master.path).resolve()
            attempt = master_path.parent.parent
            if (
                attempt.parent != task_root
                or not re.fullmatch(r"[0-9a-f]{8}", attempt.name)
                or master_path != attempt / "outputs/episode.mp4"
            ):
                return None
        return attempt
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None
