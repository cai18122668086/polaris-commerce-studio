"""Shared immutable transcript byte checks for API and worker plan imports."""

from pathlib import Path

from .errors import ApiError
from .motion_library import read_json, sha256
from .video_editing_contracts import Transcript
from .video_editing_task_models import EditingArtifactRecord, EditingTaskRecord


def read_transcript_artifact(
    record: EditingArtifactRecord | None, task: EditingTaskRecord, task_root: Path
) -> Transcript:
    if (
        task.status != "completed"
        or not record
        or record.task_id != task.id
        or record.role != "transcript"
    ):
        raise ApiError(404, "EDITING_TRANSCRIPT_NOT_FOUND", "未找到原识别记录。")
    path = Path(record.path).resolve()
    if (
        not path.is_relative_to((task_root / task.id).resolve())
        or not path.is_file()
        or path.stat().st_size != record.bytes
        or record.bytes > 2_000_000
        or sha256(path) != record.sha256
    ):
        raise ApiError(
            409, "EDITING_TRANSCRIPT_CHANGED", "识别记录已变化，请恢复原产物。"
        )
    return Transcript.model_validate(read_json(path))
