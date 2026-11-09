"""Retarget the original three-card choreography on one measured clock."""

import math
from bisect import bisect_right
from itertools import pairwise
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont

from .motion_library import sha256

CARD_GROUP = "CX-G07"
SPLIT_GROUPS = frozenset(("CX-G01", "CX-G02", "CX-G03"))
SPLIT_TITLE_FONT = "font-dab883d69fb71323"
SPLIT_ENGINE_SHA = "a0bbc920f8efda7a49e4cf0690c9276787c37763fd64d5741433ba0a49b3d54d"
SPLIT_HELPERS_SHA = "8acf164eab612f33b972e64047deb513d134b1d7d99707525358f44f106a6175"
SPLIT_WRAPPER_SHA = "aac975ae441d6377fbc1063a0900cf5808d3317f6e50765dd34e0d2d65f017ee"
CARD_ENGINE_SHA = "475a8042114fba9fef8415e05d0950c0f3a94b58a06e2bc4bffd11fe81ae3204"
CARD_TEMPLATE_SHA = "ff1a9e7fcadbb415acffc1bb610edc4b735fe2d781bdf757dead8485a1300c57"
# First in-canvas key of each original track, then the shared settled pose.
CARD_LANDMARKS = {
    "/cards/0/keys/2/0": 3,
    "/cards/1/keys/2/0": 24,
    "/cards/2/keys/2/0": 42,
    "/cards/2/keys/9/0": 54,
}


def compile_split_clock(
    package: Path, group: dict, config: dict, resources: dict[str, str]
) -> dict[str, Any]:
    """Preflight the original three-item browser entry before launching Chrome."""
    entry = package / group["entry"]
    if (
        sha256(entry) != SPLIT_ENGINE_SHA
        or sha256(entry.with_name("helpers.js")) != SPLIT_HELPERS_SHA
        or sha256(package / "commercial_runtime/special.py") != SPLIT_WRAPPER_SHA
    ):
        raise ValueError("Original browser split engine or export clock changed")
    if SPLIT_TITLE_FONT not in resources:
        raise ValueError("Bind the original browser split title font explicitly")
    duration, items = config["duration"], config["items"]
    if not math.isfinite(duration) or not 0 < duration <= 30:
        raise ValueError("Browser split duration must fit the original output clock")
    frames = round(duration * 30)
    if (
        len(items) != 3
        or any(
            not 1 <= len(item["label"]) <= 4
            or not math.isfinite(item["enter"])
            or not 0 <= item["at"] < item["at"] + item["enter"] < duration
            or item["at"] + item["enter"] > (frames - 1) / 30
            or len(item.get("english", "")) > 24
            for item in items
        )
        or any(left["at"] > right["at"] for left, right in pairwise(items))
    ):
        raise ValueError(
            "Browser split needs three ordered items that settle before export"
        )
    # Original drawing uses the explicit local clock, not this historical annotation.
    config["source_frames"] = [0, frames - 1]
    return {
        "policy": "original_three_item_split_clock",
        "engine_sha256": SPLIT_ENGINE_SHA,
        "helpers_sha256": SPLIT_HELPERS_SHA,
        "title_font_id": SPLIT_TITLE_FONT,
        "frames": frames,
        "items": [{"at": item["at"], "enter": item["enter"]} for item in items],
        "timing_review": "unreviewed",
    }


def card_font_evidence(font: Path, config: dict) -> dict[str, Any]:
    characters = {
        char
        for card in config["cards"]
        for variant in ("food", "city")
        for char in card[variant]["label"]
        if not char.isspace()
    }
    with TTFont(font, fontNumber=0) as face:
        cmap = face.getBestCmap() or {}
        if any(ord(char) not in cmap for char in characters):
            raise ValueError(
                "The selected browser card font cannot draw every bound label"
            )
    return {"font_sha256": sha256(font), "label_codepoints": len(characters)}


def compile_card_clock(
    package: Path,
    group: dict,
    template: dict,
    config: dict,
    native: dict,
) -> tuple[dict[str, float], dict[str, Any]]:
    if (
        sha256(package / group["entry"]) != CARD_ENGINE_SHA
        or sha256(package / group["input_template"]) != CARD_TEMPLATE_SHA
        or any(config[key] != template[key] for key in ("width", "height", "fps"))
    ):
        raise ValueError("Original browser card clock or canvas changed")
    clock = native["clock"]
    frames = math.ceil(
        (clock["end_ms"] - clock["start_ms"]) / 1000 * clock["native_fps"]
    )
    bound = {event["path"]: event for event in native["events"]}
    if bound.keys() != CARD_LANDMARKS.keys():
        raise ValueError(
            "Each browser card arrival and the settled pose need word anchors"
        )
    original = [0, *CARD_LANDMARKS.values(), template["frames"] - 1]
    current = [0, *(bound[key]["value"] for key in CARD_LANDMARKS), frames - 1]
    if any(left >= right for left, right in pairwise(current)):
        raise ValueError(
            "Browser landmarks need distinct ordered frames within the shot"
        )
    translated = {}
    for i, (card, fresh) in enumerate(
        zip(template["cards"], config["cards"], strict=True)
    ):
        if any(card[key] != fresh[key] for key in ("id", "width", "height")):
            raise ValueError("Preserve the original card geometry")
        for j, (key, new) in enumerate(zip(card["keys"], fresh["keys"], strict=True)):
            if key[1:] != new[1:]:
                raise ValueError("Preserve the original card poses")
            index = min(bisect_right(original, key[0]) - 1, len(original) - 2)
            progress = (key[0] - original[index]) / (
                original[index + 1] - original[index]
            )
            translated[f"/cards/{i}/keys/{j}/0"] = round(
                current[index] + progress * (current[index + 1] - current[index]), 6
            )
    return translated, {
        "policy": "shared_original_card_clock",
        "engine_sha256": CARD_ENGINE_SHA,
        "template_sha256": CARD_TEMPLATE_SHA,
        "original_landmark_frames": original,
        "current_landmark_frames": current,
        "pose_geometry_preserved": True,
        "timing_review": "unreviewed",
    }
