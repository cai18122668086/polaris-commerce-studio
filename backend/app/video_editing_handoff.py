"""Authenticated download bundle for a completed job's immutable materials."""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .config import Settings
from .errors import ApiError
from .video_generation_models import VideoGenerationRecord
from .video_template_media import video_info


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def build_manifest(row: VideoGenerationRecord) -> dict[str, Any]:
    if row.kind != "lipsync" or row.status != "completed":
        raise ApiError(409, "VIDEO_HANDOFF_NOT_READY", "口播完成后才能导出剪辑材料。")
    details = row.details
    video = Path(details.get("result_path", ""))
    audio = Path(details.get("audio_local_path", ""))
    if not video.is_file() or not audio.is_file():
        raise ApiError(
            409, "VIDEO_HANDOFF_MEDIA_MISSING", "交接素材不完整，请先恢复原任务音频。"
        )
    snapshot = details.get("snapshot", {})
    draft = snapshot.get("draft", {})
    text = draft.get("text", "") if draft.get("drive") == "text" else ""
    suffix = {"audio/mpeg": ".mp3", "audio/wav": ".wav", "audio/mp4": ".m4a"}.get(
        details.get("audio_mime") or "", audio.suffix
    )
    audio_name = "narration" + suffix
    info = video_info(video)
    manifest = {
        "schema_version": "1.0",
        "idempotency_key": row.id,
        "project_id": row.project_id,
        "generation_task_id": row.id,
        "confirmed_version_id": row.confirmed_version_id,
        "audio_duration_seconds": details.get("audio_duration_seconds"),
        "audio_format": {
            "mime_type": details.get("audio_mime"),
            "bytes": audio.stat().st_size,
            "sha256": file_digest(audio),
        },
        "video_format": {
            "mime_type": "video/mp4",
            "bytes": video.stat().st_size,
            "dimensions": list(info["size"]),
            "fps": info["fps"],
            "duration_seconds": info["duration"],
            "sha256": file_digest(video),
        },
        "files": {
            "video": "talking-head.mp4",
            "audio": audio_name,
            "script": "confirmed-script.txt" if text else None,
        },
        "script_sha256": hashlib.sha256(text.encode()).hexdigest() if text else None,
        "subtitles": {
            "status": "pending_alignment" if text else "transcription_required",
            "reference_timestamps_reusable": False,
        },
        "tts": {
            key: value
            for key, value in (details.get("tts") or {}).items()
            if key in {"voice_name", "speed", "emotion", "language_boost"}
        },
        "access": "Owner session for ZIP; expiring Bearer grant for editing service.",
    }
    return manifest


def export_bundle(row: VideoGenerationRecord, settings: Settings) -> FileResponse:
    manifest = build_manifest(row)
    video = Path(row.details["result_path"])
    audio = Path(row.details["audio_local_path"])
    text = row.details.get("snapshot", {}).get("draft", {}).get("text", "")
    audio_name = manifest["files"]["audio"]
    root = settings.video_media_dir / "handoffs"
    root.mkdir(parents=True, exist_ok=True)
    target = root / (str(uuid4()) + ".zip")
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(video, "talking-head.mp4")
            archive.write(audio, audio_name)
            if manifest["files"]["script"]:
                archive.writestr("confirmed-script.txt", text)
            archive.writestr(
                "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            archive.writestr(
                "stage-history.json",
                json.dumps(
                    row.details.get("stage_history", []), ensure_ascii=False, indent=2
                ),
            )
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return FileResponse(
        target,
        media_type="application/zip",
        filename=f"video-handoff-{row.id}.zip",
        headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(target.unlink, missing_ok=True),
    )
