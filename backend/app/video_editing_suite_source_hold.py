"""Hold the last presenter frame when the video is a hair shorter than speech.

A lipsync video can end ~35 ms before its audio (bihuo-04 e2e 2026-11-25:
377 frames at 24 fps for 15.743 s of speech). Suite runtimes sample the
presenter with ``end_policy='error'`` across ``round(duration * 25)`` frames
and failed with "Media ended before its planned window". A shortfall of at
most HOLD_FRAMES frames is padded by repeating the last frame; anything longer
is a real mismatch and still fails in the template.
"""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

from .motion_library import atomic_json, sha256
from .video_editing_pipeline import probe, run

SUITE_FPS = 25
HOLD_FRAMES = 2
# Separate, versioned prepare step: bihuo_suite/source.py is part of the
# template identity, so it is not edited; this step runs after it.
VERSION = "tengli.suite-source-hold/1"


def video_shortfall(info: dict[str, Any], duration: float) -> float:
    """Seconds the last decodable frame ends before the suite's last frame."""
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    fps = Fraction(video.get("avg_frame_rate") or "0/1")
    frames = int(video.get("nb_frames") or 0)
    if fps <= 0:
        return 0.0
    if frames <= 0:
        frames = round(float(video.get("duration") or 0) * fps)
    if frames <= 0:
        return 0.0
    needed = max(0, round(duration * SUITE_FPS) - 1) / SUITE_FPS
    return needed - float((frames - 1) / fps)


def hold_tail(
    source: Path, duration: float, root: Path, settings: Any, guard: Any
) -> Path:
    shortfall = video_shortfall(probe(source, settings), duration)
    if shortfall <= 1e-6 or shortfall > HOLD_FRAMES / SUITE_FPS + 1e-6:
        return source
    target = root / "suite-source-held.mp4"
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
            f"tpad=stop_mode=clone:stop_duration={(HOLD_FRAMES + 1) / SUITE_FPS}",
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
            "copy",
            "-movflags",
            "+faststart",
            str(target),
        ],
        root,
        settings,
        guard,
        "hold_suite_source_tail",
    )
    atomic_json(
        root / "suite-source-hold.json",
        {
            "source_sha256": sha256(source),
            "held_sha256": sha256(target),
            "shortfall_seconds": round(shortfall, 4),
            "version": VERSION,
            "required_frames": round(duration * SUITE_FPS),
            "policy": f"hold last frame for at most {HOLD_FRAMES} frames",
        },
    )
    return target
