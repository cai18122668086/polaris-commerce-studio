"""Prepare the native geometry once while preserving the original speech clock."""

from fractions import Fraction
from pathlib import Path
from typing import Any

from ..motion_library import atomic_json, sha256
from ..video_editing_pipeline import probe, run


def prepare(
    source: Path, duration: float, root: Path, settings: Any, guard: Any
) -> Path:
    video = next(
        s for s in probe(source, settings)["streams"] if s["codec_type"] == "video"
    )
    fps = Fraction(video.get("avg_frame_rate", "0/1"))
    rotation = video.get("tags", {}).get("rotate", "0")
    rotated = any(
        row.get("rotation", 0) % 360 for row in video.get("side_data_list", [])
    )
    if (
        (video["width"], video["height"]) == (1080, 1920)
        and fps == 25
        and int(rotation) % 360 == 0
        and not rotated
        and video.get("sample_aspect_ratio", "1:1") in {"1:1", "N/A"}
    ):
        return source
    original_sha = sha256(source)
    target = root / "suite-source.mp4"
    run(
        [
            settings.video_editing_ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            "scale=1080:1920:flags=lanczos,setsar=1,fps=25",
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(target),
        ],
        root,
        settings,
        guard,
        "prepare_suite_source",
    )
    if sha256(source) != original_sha:
        raise ValueError("Original source changed during native preparation")
    atomic_json(
        root / "suite-source-receipt.json",
        {
            "original_sha256": original_sha,
            "prepared_sha256": sha256(target),
            "duration_seconds": duration,
            "size": [1080, 1920],
            "fps": 25,
            "speech_clock": "unchanged; no transcript or alignment regeneration",
        },
    )
    return target
