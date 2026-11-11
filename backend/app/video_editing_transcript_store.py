"""Shared immutable transcript byte checks for API and worker plan imports."""

from pathlib import Path

from .errors import ApiError
from .motion_library import read_json, sha256
from .video_editing_contracts import EditingSourceFrame, Transcript
from .video_editing_task_models import EditingArtifactRecord, EditingTaskRecord

MAX_TRANSCRIPT_BYTES = 2_000_000


def recorded_source_frame(record: EditingArtifactRecord) -> EditingSourceFrame | None:
    data = record.validation.get("source_frame")
    return EditingSourceFrame.model_validate(data) if data is not None else None


def require_native_source_frame(frame: EditingSourceFrame | None) -> None:
    if frame is not None and not frame.supports_native_portrait:
        raise ApiError(
            409,
            "EDITING_ORIENTATION_REVIEW_REQUIRED",
            f"当前原片为 {frame.width}×{frame.height}，"
            "原生模板需要方形像素的 9:16 竖屏原片。",
        )


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
        or record.bytes > MAX_TRANSCRIPT_BYTES
        or sha256(path) != record.sha256
    ):
        raise ApiError(
            409, "EDITING_TRANSCRIPT_CHANGED", "识别记录已变化，请恢复原产物。"
        )
    return Transcript.model_validate(read_json(path))
