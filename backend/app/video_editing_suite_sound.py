"""Attach library effects to the first three reviewed native suite clocks."""

import math
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import cv2

from .video_editing_pipeline import run
from .video_editing_screen_clicks import detect_screen_clicks
from .video_editing_sound_palettes import select_sound
from .video_editing_tutorial_sound import write_cue_track

SUITE_FAMILIES = {
    "bihuo-33-v1": "news",
    "bihuo-04-v1": "application",
    "bihuo-10-v1": "lifestyle",
}


def suite_actions(family: str, cfg: dict) -> list[tuple[float, str]]:
    actions = [(0.08, "opening")]
    actions.extend((row["start"], "media") for row in cfg.get("materials", []))
    for row in cfg.get("captions", []):
        if any(line.get("emphasis_spans") for line in row.get("lines", [])):
            actions.append((row["time"][0], "emphasis"))
    if family == "news":
        if cfg.get("title") or cfg.get("subtitle"):
            actions.append((cfg["opening_end"] * 8 / 77, "type"))
        actions.extend((row["start"], "text") for row in cfg["text_items"])
        if cfg["conclusion"]:
            actions.append((cfg["final_start"], "closing"))
    elif family == "application":
        for scene in cfg["chapters"]:
            actions.extend((row["enter_at"], "text") for row in scene.get("items", []))
            for row in scene.get("contrast", []):
                actions.append((row["phase"][0], "emphasis"))
            quote = scene.get("quote") or {}
            for part in ("first", "second"):
                if quote.get(part):
                    actions.append((quote[f"{part}_at"], "type"))
    else:
        if cfg["star_count"]:
            actions.append((cfg["stars_at"] + 1 / cfg["fps"], "confirm"))
        if cfg["wipe_at"] is not None:
            actions.append((cfg["wipe_at"], "transition"))
        card = cfg["card"]
        if card["enabled"]:
            actions.extend((row["at"], "text") for row in card["items"])
            if card["button"]:
                actions.append((card["button_at"], "closing"))
    return actions


def enhance_suite_sound(
    base: Path,
    payload: dict,
    duration_ms: int,
    series: str,
    root: Path,
    settings,
    guard: Callable[[], None],
    *,
    scan_recordings: bool,
) -> tuple[Path, dict]:
    family = SUITE_FAMILIES[payload["template_id"]]
    cfg = payload["config"]
    fps = cfg["fps"]
    actions = suite_actions(family, cfg)
    if family == "application" and scan_recordings:
        for material in cfg.get("materials", []):
            if material.get("type") != "video":
                continue
            window_ms = round((material["end"] - material["start"]) * 1000)
            try:
                clicks = detect_screen_clicks(Path(material["path"]), window_ms, guard)
            except cv2.error:
                clicks = []
            source_start = round(material["start"] * fps) / fps
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
        selections.append((at, selection))
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
