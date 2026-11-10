"""Bind script provenance to narration sources and inspect their audio clocks."""

import math
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .errors import ApiError
from .motion_library import sha256
from .video_editing_pipeline import probe
from .video_editing_task_models import EditingSourceRecord
from .video_generation_models import VideoGenerationRecord
from .video_studio_models import VideoScriptVersionRecord
from .video_writing_provenance import (
    matching_writing_origin,
    script_digest,
    spoken_script,
)

START_TOLERANCE_MS = 50
DURATION_TOLERANCE_MS = 100


def script_reference(version: VideoScriptVersionRecord | None) -> str | None:
    return spoken_script(version.snapshot) if version else None


def uploaded_script_reference(
    version: VideoScriptVersionRecord,
) -> dict[str, Any] | None:
    writing_origin = matching_writing_origin(version.writing_origin, version.snapshot)
    if version.writing_origin is not None and writing_origin is None:
        return None
    return {
        "schema": "tengli.editing-upload-script-reference/1",
        "script_sha256": script_digest(script_reference(version)),
        **({"writing_origin": writing_origin} if writing_origin else {}),
    }


def freeze_generation_source(
    job: VideoGenerationRecord, version: VideoScriptVersionRecord | None
) -> dict[str, Any]:
    if job.confirmed_version_id and (
        version is None
        or version.id != job.confirmed_version_id
        or version.project_id != job.project_id
        or version.kind != "confirmed"
    ):
        raise ApiError(
            409, "EDITING_GENERATION_SCRIPT_CHANGED", "口播任务的确认稿已不可用。"
        )
    reference = script_reference(version)
    writing_origin = None
    if version and version.writing_origin is not None:
        writing_origin = matching_writing_origin(
            version.writing_origin, version.snapshot
        )
        if writing_origin is None:
            raise ApiError(
                409, "EDITING_GENERATION_SCRIPT_CHANGED", "确认稿正文与写稿来源不一致。"
            )
    draft = job.details.get("snapshot", {}).get("draft")
    if version and draft:
        confirmed = version.snapshot.get("draft", {})
        if draft.get("drive") != confirmed.get("drive") or (
            confirmed.get("drive") != "audio"
            and draft.get("text") != confirmed.get("text")
        ):
            raise ApiError(
                409,
                "EDITING_GENERATION_SCRIPT_CHANGED",
                "口播任务与原确认稿内容不一致。",
            )

    declared = job.details.get("audio_local_path")
    voice: dict[str, Any] = {"status": "not_recorded"}
    if isinstance(declared, str) and declared:
        path = Path(declared)
        try:
            voice = (
                {"status": "bound", "path": str(path.resolve()), "sha256": sha256(path)}
                if path.is_file()
                else {"status": "missing"}
            )
        except (OSError, ValueError):
            voice = {"status": "missing"}

    return {
        "schema": "tengli.editing-generation-source/1",
        "script_sha256": script_digest(reference),
        "generation_script_snapshot": "matched"
        if version and draft
        else "not_recorded",
        "voice": voice,
        **({"writing_origin": writing_origin} if writing_origin else {}),
    }


def source_origin(source: EditingSourceRecord) -> dict[str, Any]:
    key = (
        "confirmed_script_reference"
        if source.kind == "upload_asset"
        else "generation_lineage"
    )
    lineage = source.details.get(key) or {}
    return {
        "kind": source.kind,
        "confirmed_version_id": source.confirmed_version_id,
        "generation_task_id": source.generation_task_id,
        "media_sha256": source.media_sha256,
        "script_sha256": lineage.get("script_sha256"),
        **(
            {"writing_origin": lineage["writing_origin"]}
            if lineage.get("writing_origin")
            else {}
        ),
    }


def audio_clock(info: dict) -> dict[str, int] | None:
    streams = info.get("streams", [])
    stream = next((row for row in streams if row.get("codec_type") == "audio"), None)
    if stream is None:
        return None
    try:
        # Some audio-only formats store timing in the container instead of the stream.
        container = info.get("format", {}) if len(streams) == 1 else {}
        raw_start = stream.get("start_time", container.get("start_time"))
        if raw_start is None and container.get("format_name") == "wav":
            # WAV PCM has no stored time offset.
            raw_start = 0
        start = float(raw_start)
        duration = float(stream.get("duration", container.get("duration")))
        if not math.isfinite(start) or not math.isfinite(duration) or duration <= 0:
            return None
        return {"start_ms": round(start * 1000), "duration_ms": round(duration * 1000)}
    except (TypeError, ValueError):
        return None


def review_voice_clock(
    voice: dict, embedded: dict | None, settings: Settings, guard: Callable[[], None]
) -> dict:
    if voice["status"] != "bound":
        return {"status": voice["status"]}
    expected = voice["sha256"]
    path = Path(voice["path"])
    try:
        guard()
        if not path.is_file() or sha256(path) != expected:
            return {"status": "bytes_changed", "sha256": expected}
        separate = audio_clock(probe(path, settings, formats="mp3,wav,mov"))
        guard()
        if sha256(path) != expected:
            return {"status": "bytes_changed", "sha256": expected}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "clock_unavailable", "sha256": expected}
    if not embedded or not separate:
        return {"status": "clock_unavailable", "sha256": expected}
    start = separate["start_ms"] - embedded["start_ms"]
    duration = separate["duration_ms"] - embedded["duration_ms"]
    return {
        "status": (
            "clock_matched"
            if abs(start) <= START_TOLERANCE_MS
            and abs(duration) <= DURATION_TOLERANCE_MS
            else "clock_differs"
        ),
        "sha256": expected,
        "clock": separate,
        "delta_from_video_audio_ms": {"start": start, "duration": duration},
        "tolerance_ms": {
            "start": START_TOLERANCE_MS,
            "duration": DURATION_TOLERANCE_MS,
        },
    }


def generation_source_receipt(
    origin: dict,
    lineage: dict,
    prepared: dict,
    settings: Settings,
    guard: Callable[[], None],
) -> dict:
    embedded = audio_clock(prepared["probe"])
    return {
        "schema": "tengli.editing-source-receipt/1",
        "source": origin,
        "generation_script_snapshot": lineage["generation_script_snapshot"],
        "selected_audio": "original_video_audio",
        "embedded_audio_clock": embedded,
        "embedded_asr_pcm_sha256": prepared["audio_sha256"],
        "separate_voice": review_voice_clock(
            lineage["voice"], embedded, settings, guard
        ),
        "separate_voice_used": False,
        "speech_stretched": False,
    }


def upload_source_receipt(origin: dict, prepared: dict) -> dict:
    return {
        "schema": "tengli.editing-upload-source-receipt/1",
        "source": origin,
        "confirmed_script_role": "reference_only",
        "selected_audio": "original_video_audio",
        "embedded_audio_clock": audio_clock(prepared["probe"]),
        "embedded_asr_pcm_sha256": prepared["audio_sha256"],
        "speech_stretched": False,
    }
