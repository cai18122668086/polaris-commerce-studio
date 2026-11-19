"""Attach library effects to the native suite clocks."""

import math
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import cv2

from .config import Settings
from .video_editing_pipeline import run
from .video_editing_screen_clicks import detect_screen_clicks
from .video_editing_sound_palettes import select_sound
from .video_editing_suite_actions import (
    SUITE_FAMILIES,
    recording_windows,
    suite_actions,
)
from .video_editing_tutorial_sound import write_cue_track


def enhance_suite_sound(
    base: Path,
    payload: dict,
    duration_ms: int,
    series: str,
    root: Path,
    settings: Settings,
    guard: Callable[[], None],
    *,
    scan_recordings: bool,
) -> tuple[Path, dict]:
    template_id = payload["template_id"]
    family = SUITE_FAMILIES[template_id]
    cfg = payload["config"]
    fps = cfg.get("fps", 25)
    actions = suite_actions(template_id, cfg)
    if scan_recordings:
        for material, window_ms, source_start in recording_windows(template_id, cfg):
            try:
                clicks = detect_screen_clicks(Path(material["path"]), window_ms, guard)
            except cv2.error:
                clicks = []
            actions.extend(
                (source_start + row["source_ms"] / 1000, "click") for row in clicks
            )
    occurrences: Counter[str] = Counter()
    events = []
    selections = []
    previous_ms = -1000
    previous_sound = ""
    for start, action in sorted(actions, key=lambda row: (row[0], row[1] != "media")):
        at = round(math.ceil(start * fps - 1e-7) / fps * 1000)
        if (
            at < 0
            or duration_ms - at < 90
            or (at - previous_ms < 70 and action != "click")
        ):
            continue
        selection = select_sound(
            family, action, series, occurrences[action], previous=previous_sound
        )
        if selection is None:
            continue
        occurrences[action] += 1
        asset_id, source_at, length, peak = selection
        selections.append((at, (asset_id, source_at, length, peak + 5.5)))
        events.append({"at_ms": at, "action": action, "asset_id": selection[0]})
        previous_ms, previous_sound = at, selection[0]
    root.mkdir(parents=True, exist_ok=True)
    track = root / "sound-effects.wav"
    write_cue_track(track, duration_ms, selections, settings, guard)
    final = root / "final.mp4"
    run(
        [
            settings.video_editing_ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-i",
            str(base),
            "-i",
            str(track),
            "-filter_complex",
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo[voice];"
            "[1:a]aformat=channel_layouts=stereo[fx];"
            "[voice][fx]amix=inputs=2:duration=first:normalize=0,"
            "alimiter=limit=0.97:level=0:latency=1[audio]",
            "-map",
            "0:v:0",
            "-map",
            "[audio]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(final),
        ],
        root,
        settings,
        guard,
        "suite_audio",
    )
    return final, {"family": family, "events": events}
