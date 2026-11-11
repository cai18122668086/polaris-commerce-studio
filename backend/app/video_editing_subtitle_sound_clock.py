"""Align a word-bound subtitle entry cue using the native renderer's alpha frames."""

import hashlib
import importlib
import io
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from .motion_library import read_json, sha256

SUBTITLE_ENTRY_SYNC = "rgba-threshold-v1"
_ALPHA_THRESHOLD = 96
_MIN_VISIBLE_PIXELS = 100
_SEARCH_AFTER_EVENT_FRAMES = 6
_NATIVE_SOURCES = {
    "episode.py": "ec5115f41bbb44c034bccc66b06169f92a389d4a270eea8c6c6cd1d2e3472038",
    "layout.py": "54dd2899595aeb68859d6c5e5e00cfd25a44e43e021df3639edf315d27ee1d88",
    "sound.py": "1ca650f9572847b98071cf331120c34b6fb8dc01377c5858d5cba6ad1316e810",
}


def subtitle_entry_clock(
    root: Path, episode: dict, cue: dict, receipts: list[dict]
) -> dict[str, Any]:
    """Measure the first visible source frame on the pinned compositor's clock."""
    ref = cue["anchor_ref"]
    index = ref["shot_index"]
    shot, receipt = episode["shots"][index], receipts[index]
    group = shot["group_id"]
    fps = episode["output"]["fps"]
    local_event = cue["word_binding"]["value"]
    if (
        cue["subtitle_entry_sync"] != SUBTITLE_ENTRY_SYNC
        or cue["phase"] != "entry"
        or ref["unit"] != "frames"
        or type(local_event) is not int
        or local_event < 0
        or shot["layer"] != "subtitle"
        or cue["group_id"] != group
        or receipt["group_id"] != group
        or receipt["decoded"] is not True
        or fps != 30
        or receipt["native"]["fps"] != fps
    ):
        raise ValueError(
            "Subtitle sound sync requires a verified 30 fps native word event"
        )
    folder = root.resolve() / "renders" / f"{index:03}-{group}-rgba"
    manifest = folder / "sequence.json"
    if Path(receipt["rgba_sequence"]) != folder or manifest.resolve() != manifest:
        raise ValueError("Subtitle sound frames must belong to the current shot")
    sequence = read_json(manifest)
    frames = sequence["frames"]
    size = (sequence["width"], sequence["height"])
    if (
        sequence["fps"] != fps
        or len(frames) != receipt["native"]["frames"]
        or size != (receipt["native"]["width"], receipt["native"]["height"])
    ):
        raise ValueError("Subtitle sound sequence does not match the native clock")
    origin = round(shot["start_seconds"] * 1000) * fps
    enabled_frame = (origin + 999) // 1000
    first_enabled = enabled_frame - origin // 1000
    limit = local_event + _SEARCH_AFTER_EVENT_FRAMES + 1
    for number, row in enumerate(frames[first_enabled:limit], start=first_enabled):
        frame = folder / f"{number:06}.png"
        if (
            row["frame"] != number
            or row["path"] != frame.name
            or frame.resolve() != frame
        ):
            raise ValueError("Subtitle sound frames must retain their native order")
        contents = frame.read_bytes()
        if hashlib.sha256(contents).hexdigest() != row["sha256"]:
            raise ValueError("Subtitle sound frame changed after native rendering")
        with Image.open(io.BytesIO(contents)) as image:
            if image.format != "PNG" or image.mode != "RGBA" or image.size != size:
                raise ValueError("Subtitle sound frame needs its original RGBA format")
            visible = sum(image.getchannel("A").histogram()[_ALPHA_THRESHOLD + 1 :])
        if visible <= _MIN_VISIBLE_PIXELS:
            continue
        # The native setpts truncates the positive fractional shot origin and
        # the overlay enable expression still gates the start of the shot.
        output_frame = origin // 1000 + number
        if output_frame / fps >= shot["end_seconds"]:
            break
        return {
            "shot_index": index,
            "native_frame": number,
            "output_frame": output_frame,
            "frame_sha256": row["sha256"],
            # Some original entry cues mark an emphasis of text already on screen.
            "aligned_to_frame": number >= local_event,
        }
    raise ValueError("No visible native subtitle frame near the word-bound entry")


def install_subtitle_sound_clock(package: Path, root: Path) -> None:
    plan_path = root / "audio-plan.json"
    if not plan_path.is_file():
        return
    plan = read_json(plan_path)["fx"]
    if not any(cue.get("subtitle_entry_sync") for cue in plan):
        return
    native_root = package / "commercial_runtime"
    if any(
        sha256(native_root / name) != digest for name, digest in _NATIVE_SOURCES.items()
    ):
        raise ValueError("Pinned original subtitle composition or sound clock changed")
    sys.path.insert(0, str(package))
    try:
        layout: Any = importlib.import_module("commercial_runtime.layout")
    finally:
        sys.path.pop(0)
    if Path(layout.__file__).resolve() != native_root / "layout.py":
        raise ValueError("Subtitle sound sync needs the pinned native layout module")
    original = layout.review

    def review(data: dict, instance: Path, receipts: list[dict] | None = None) -> dict:
        result = original(data, instance, receipts)
        if Path(instance) != root or receipts is None or result["status"] != "passed":
            raise ValueError(
                "Subtitle sound sync needs successful native layout evidence"
            )
        for cue, event in zip(plan, data["fx"], strict=True):
            if not cue.get("subtitle_entry_sync"):
                continue
            if any(
                event[key] != cue[key]
                for key in ("anchor_ref", "anchor_seconds", "asset_id")
            ):
                raise ValueError(
                    "Subtitle sound cue differs from the word-bound native input"
                )
            clock = subtitle_entry_clock(root, data, cue, receipts)
            if clock["aligned_to_frame"]:
                onset = clock["output_frame"] / data["output"]["fps"]
                length = min(
                    event["trim_duration_seconds"],
                    data["source"]["duration_seconds"] - onset,
                )
                if length < 0.06:
                    raise ValueError(
                        "Not enough audio remains after the subtitle entry frame"
                    )
                event.pop("anchor_ref")
                event.update(anchor_seconds=onset, trim_duration_seconds=length)
        return result

    layout.review = review
