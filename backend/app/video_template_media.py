"""Local media preparation shared by the worker and the verification CLI."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import imageio_ffmpeg

from .errors import ApiError


def run_media(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", *args],
            check=True,
            capture_output=True,
            timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (subprocess.SubprocessError, OSError):
        raise ApiError(
            422, "VIDEO_MEDIA_PROCESSING_FAILED", "媒体处理未完成，可保留原任务重试。"
        ) from None


def audio_duration(path: Path) -> float:
    # Count decoded samples through continuous timestamps; provider estimates and
    # MP3 header padding are not used to determine the required video duration.
    result = run_media(
        [
            "-xerror",
            "-progress",
            "pipe:1",
            "-nostats",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-vn",
            "-af",
            "aresample=16000,asetpts=N/SR/TB",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "null",
            "-",
        ]
    )
    values = [
        int(line.split("=", 1)[1])
        for line in result.stdout.decode().splitlines()
        if line.startswith("out_time_us=") and line.split("=", 1)[1].isdigit()
    ]
    seconds = max(values, default=0) / 1_000_000
    if seconds <= 0 or not math.isfinite(seconds):
        raise ApiError(422, "VIDEO_AUDIO_DURATION_INVALID", "无法测量音频实际时长。")
    return seconds


def video_info(path: Path) -> dict[str, Any]:
    reader = None
    try:
        reader = imageio_ffmpeg.read_frames(
            str(path), input_params=["-protocol_whitelist", "file,pipe"]
        )
        info = next(reader)
        if not all(math.isfinite(info[k]) and info[k] > 0 for k in ["fps", "duration"]):
            raise ValueError("Invalid video timing")
        return info
    except (RuntimeError, OSError, ValueError, StopIteration, KeyError):
        raise ApiError(422, "VIDEO_TEMPLATE_INVALID", "动作模板无法读取。") from None
    finally:
        if reader is not None:
            reader.close()


def prepare_forward(
    source: Path, target: Path, seconds: float, dissolve: float = 0.25
) -> dict[str, Any]:
    """Cover the decoded audio length using a bounded number of FFmpeg inputs.

    Make one cyclic clip, blending its tail into its head, then stream-loop it.
    The cycle starts just after the head used in the dissolve, so the seam joins
    matching forward poses. Rendering cost does not require an input per repeat.
    """
    if (
        source.resolve() == target.resolve()
        or not math.isfinite(seconds)
        or seconds <= 0
    ):
        raise ApiError(422, "VIDEO_TEMPLATE_DURATION_INVALID", "动作时长无效。")
    info = video_info(source)
    fps = info["fps"]
    duration = math.floor(info["duration"] * fps + 1e-6) / fps
    if duration <= 0 or not math.isfinite(dissolve) or dissolve <= 0:
        raise ApiError(422, "VIDEO_TEMPLATE_INVALID", "动作模板过短或无法处理。")
    frames = math.ceil(seconds * fps - 1e-7)
    target_seconds = frames / fps
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.stem + "." + str(uuid4()) + ".mp4")
    cycle = target.with_name(target.stem + ".cycle-" + str(uuid4()) + ".mp4")
    fade = min(max(1, round(dissolve * fps)) / fps, duration / 4)
    try:
        if seconds <= duration:
            run_media(
                [
                    "-y",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(source),
                    "-vf",
                    f"fps={fps},format=yuv420p",
                    "-frames:v",
                    str(frames),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-movflags",
                    "+faststart",
                    str(temporary),
                ]
            )
        else:
            graph = (
                f"[0:v]fps={fps},settb=AVTB,split=2[body][head];"
                f"[body]trim=start={fade}:end={duration},setpts=PTS-STARTPTS[b];"
                f"[head]trim=end={fade},setpts=PTS-STARTPTS[h];"
                f"[b][h]xfade=transition=fade:duration={fade}:"
                f"offset={duration - 2 * fade},format=yuv420p[out]"
            )
            run_media(
                [
                    "-y",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(source),
                    "-filter_complex_threads",
                    "1",
                    "-filter_complex",
                    graph,
                    "-map",
                    "[out]",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-movflags",
                    "+faststart",
                    str(cycle),
                ]
            )
            run_media(
                [
                    "-y",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-stream_loop",
                    "-1",
                    "-i",
                    str(cycle),
                    "-frames:v",
                    str(frames),
                    "-an",
                    "-c:v",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(temporary),
                ]
            )
        measured = video_info(temporary)["duration"]
        # ffmpeg's container duration display is rounded to hundredths. Leave
        # at most half a display tick; the target was rounded up to a full frame.
        if measured + 0.005 < seconds:
            raise ApiError(422, "VIDEO_TEMPLATE_TOO_SHORT", "动作模板未覆盖完整音频。")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
        cycle.unlink(missing_ok=True)
    return {
        "recipe": "forward-cycle-v1",
        "audio_seconds": seconds,
        "target_seconds": target_seconds,
        "source_seconds": duration,
        "fps": fps,
        "target_frames": frames,
        "dissolve_seconds": fade,
        "cycle_seconds": duration - fade,
        "source_start_seconds": fade,
        "reversed_frames": False,
    }
