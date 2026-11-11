"""Create a small review proxy from the already validated native master."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .config import Settings
from .motion_library import atomic_json, sha256
from .video_editing_pipeline import EditingFailure, decode_av, probe, run

PROXY_MAX_EDGE = 640


def build_preview(
    master: Path,
    root: Path,
    validation: dict,
    settings: Settings,
    guard: Callable[[], None],
) -> tuple[Path, dict[str, Any]]:
    def tracks(path: Path) -> dict[str, dict]:
        streams = probe(path, settings)["streams"]
        by_kind = {stream["codec_type"]: stream for stream in streams}
        if len(streams) != 2 or set(by_kind) != {"video", "audio"}:
            raise EditingFailure("EDITING_PREVIEW_TRACKS_INVALID")
        return by_kind

    def audio_digest(path: Path) -> str:
        log = run(
            [
                settings.video_editing_ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-c:a",
                "copy",
                "-f",
                "hash",
                "-hash",
                "sha256",
                "-",
            ],
            root,
            settings,
            guard,
            "preview_audio_hash",
        )
        match = re.fullmatch(r"SHA256=([a-f0-9]{64})", log.read_text("ascii").strip())
        if not match:
            raise EditingFailure("EDITING_PREVIEW_AUDIO_CHANGED")
        return match[1]

    master_tracks = tracks(master)
    video = master_tracks["video"]
    factor = min(1, PROXY_MAX_EDGE / max(video["width"], video["height"]))
    width = max(2, int(video["width"] * factor / 2) * 2)
    height = max(2, int(video["height"] * factor / 2) * 2)
    preview = root / "outputs/preview.mp4"
    run(
        [
            settings.video_editing_ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-n",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(master),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            f"scale={width}:{height}:flags=lanczos,setsar=1",
            "-fps_mode",
            "passthrough",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "27",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(preview),
        ],
        root,
        settings,
        guard,
        "build_preview",
    )
    preview_tracks = tracks(preview)
    proxy = preview_tracks["video"]
    if (
        (proxy["width"], proxy["height"]) != (width, height)
        or any(proxy[key] != video[key] for key in ("avg_frame_rate", "nb_frames"))
        or any(
            abs(float(preview_tracks[kind][key]) - float(master_tracks[kind][key]))
            > 0.002
            for kind in ("video", "audio")
            for key in ("start_time", "duration")
        )
    ):
        raise EditingFailure("EDITING_PREVIEW_CLOCK_CHANGED")
    audio = audio_digest(preview)
    if audio != audio_digest(master):
        raise EditingFailure("EDITING_PREVIEW_AUDIO_CHANGED")
    decode_av(preview, root, settings, guard, "decode_preview")
    receipt = {
        "version": "tengli.review-proxy/1",
        "native_render_sha256": validation["sha256"],
        "sha256": sha256(preview),
        "duration_ms": validation["duration_ms"],
        "width": width,
        "height": height,
        "master_width": video["width"],
        "master_height": video["height"],
        "fps": proxy["avg_frame_rate"],
        "frames": int(proxy["nb_frames"]),
        "encoded_audio_sha256": audio,
        "decoded": True,
        "visual_review": "unreviewed",
        "listening_review": "unreviewed",
    }
    atomic_json(root / "preview-validation.json", receipt)
    return preview, receipt
