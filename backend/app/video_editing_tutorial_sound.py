"""Place verified library cues on a recording's final tutorial clock."""

import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .motion_library import inside, read_json, sha256
from .video_editing_pipeline import run
from .video_editing_screen_clicks import detect_screen_clicks
from .video_editing_template_audio import SCREEN_CLICK, SCREEN_ENTRY, SoundSlice
from .video_editing_tutorial_plan import playback_elapsed_ms

RATE = 48_000
VERSION = "tengli.tutorial-sound/1"


def _cue_wave(
    cue: SoundSlice, root: Path, settings: Any, guard: Callable[[], None]
) -> np.ndarray:
    asset_id, start, duration, target = cue
    package = settings.video_editing_library_dir
    assets = read_json(package / "asset-manifest.json")["assets"]
    item = next(row for row in assets if row["id"] == asset_id)
    source = inside(package, item["path"])
    if item["kind"] != "sfx" or sha256(source) != item["sha256"]:
        raise ValueError("Recording cue asset changed")
    target_file = root / f"{asset_id}.f32"
    run(
        [
            settings.video_editing_ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-ss",
            str(start),
            "-i",
            str(source),
            "-t",
            str(duration),
            "-ac",
            "1",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            str(target_file),
        ],
        root,
        settings,
        guard,
        "decode_tutorial_cue",
    )
    samples = np.fromfile(target_file, "<f4")
    peak = float(np.max(np.abs(samples), initial=0))
    if not np.isfinite(samples).all() or peak < 0.001:
        raise ValueError("Recording cue has no usable signal")
    audible = np.flatnonzero(np.abs(samples) >= peak * 0.12)[0]
    samples = samples[max(0, audible - 96) :].copy() * (10 ** (target / 20) / peak)
    tail = min(len(samples) // 2, 960)
    if tail:
        samples[-tail:] *= np.linspace(1, 0, tail)
    return samples


def write_cue_track(
    output: Path,
    duration_ms: int,
    events: list[tuple[int, SoundSlice]],
    settings: Any,
    guard: Callable[[], None],
) -> None:
    sounds = {
        cue: _cue_wave(cue, output.parent, settings, guard)
        for cue in dict.fromkeys(cue for _, cue in events)
    }
    total = round(duration_ms * RATE / 1000)
    cues = [(round(at * RATE / 1000), sounds[cue]) for at, cue in events]
    with wave.open(str(output), "wb") as writer:
        writer.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        for start in range(0, total, RATE):
            guard()
            block = np.zeros(min(RATE, total - start), dtype=np.float32)
            stop = start + len(block)
            for position, cue in cues:
                first, last = max(start, position), min(stop, position + len(cue))
                if first < last:
                    block[first - start : last - start] += cue[
                        first - position : last - position
                    ]
            writer.writeframesraw(
                np.round(np.clip(block, -1, 1) * 32767).astype("<i2").tobytes()
            )


def recording_sound(
    clock: dict,
    assets: dict,
    root: Path,
    settings: Any,
    guard: Callable[[], None],
) -> tuple[Path, dict]:
    events: list[dict] = []
    for step in clock["steps"]:
        asset_id = step["asset_id"]
        events.append(
            {
                "asset_id": asset_id,
                "at_ms": step["start_ms"],
                "evidence": "recording_entry",
            }
        )
        try:
            clicks = detect_screen_clicks(
                Path(assets[asset_id]["path"]), step["source_out_ms"], guard
            )
        except cv2.error:
            clicks = []
        events.extend(
            {
                "asset_id": asset_id,
                "at_ms": step["start_ms"]
                + playback_elapsed_ms(step["playback_segments"], click["source_ms"]),
                **click,
            }
            for click in clicks
            if step["source_in_ms"] <= click["source_ms"] < step["source_out_ms"]
        )
    selections = [
        (
            event["at_ms"],
            SCREEN_ENTRY if event["evidence"] == "recording_entry" else SCREEN_CLICK,
        )
        for event in events
    ]
    output = root / "recording-fx.wav"
    write_cue_track(output, clock["duration_ms"], selections, settings, guard)
    return output, {
        "version": VERSION,
        "native_mix_retained": True,
        "events": events,
        "detected_clicks": sum("source_ms" in event for event in events),
        "fx_sha256": sha256(output),
    }
