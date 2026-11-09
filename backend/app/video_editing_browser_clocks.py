"""Retarget the original three-card choreography on one measured clock."""

import math
from bisect import bisect_right
from itertools import pairwise
from pathlib import Path
from typing import Any

from .motion_library import sha256

CARD_GROUP = "CX-G07"
FRUIT_LIST_GROUP = "CX-G06"
FRUIT_LIST_FONTS = (
    "font-346c3d9c8c827faa",
    "font-e4b3b9d058750fb8",
    "font-aa4560dd8fe56457",
    "font-b24aa49a4bcb99a0ffc6",
    "font-91046862e08fbade0bdd",
)
_FRUIT_LIST_ENGINE = "4baf10834bdffb26e50b541cd5f91803cbddf4c1267f7e393f67a47a1cb56eaa"
_FRUIT_LIST_LEGACY = "c048cf200d0ebeb794017699c922cb92051a7c0096a63e6b95cf1c8882a02d51"
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
    from fontTools.ttLib import TTFont

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


def audit_card_family_engine(package: Path, group: dict) -> None:
    entry = package / group["entry"]
    if (
        sha256(entry) != _FRUIT_LIST_ENGINE
        or sha256(entry.parent / "legacy/src/renderer.html") != _FRUIT_LIST_LEGACY
        or sha256(package / "commercial_runtime/special.py") != SPLIT_WRAPPER_SHA
    ):
        raise ValueError("Original G04–G06 browser engine or export clock changed")


def compile_fruit_list_clock(
    package: Path,
    group: dict,
    config: dict,
    resources: dict[str, str],
    native: dict,
    assets: dict[str, dict],
) -> dict[str, Any]:
    audit_card_family_engine(package, group)
    if set(FRUIT_LIST_FONTS) - resources.keys():
        raise ValueError("Bind the five original fruit list fonts explicitly")
    frames = round(config["duration"] * 30)
    items = config["items"]
    starts = [item["at"] for item in items]
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    paths = ["/presenter", *(f"/items/{i}/image" for i in range(3))]
    if (
        len(items) != 3
        or config["background"] is not None
        or any(left >= right for left, right in pairwise(starts))
        or any(
            not math.isfinite(start) or start < 0 or start * 30 + 16 > frames - 1
            for start in starts
        )
        or set(media) != set(paths)
        or any(
            assets[media[path]].get("kind") != "image"
            or assets[media[path]].get("source") != "project_upload"
            for path in paths
        )
        or len({assets[media[path]]["sha256"] for path in paths}) != 4
        or assets[media["/presenter"]].get("width", 0) < 1006
        or assets[media["/presenter"]].get("height", 0) < 814
    ):
        raise ValueError(
            "The fruit list needs four distinct current images and time to settle"
        )
    for i, item in enumerate(items):
        prefix = f"/items/{i}/"
        label, description, arrival = (
            text.get(prefix + "label"),
            text.get(prefix + "description"),
            events.get(prefix + "at"),
        )
        if (
            not label
            or not description
            or not arrival
            or arrival["edge"] != "start"
            or arrival["token_id"] != label["token_ids"][0]
            or not 1 <= len(item["label"]) <= 3
            or not 1 <= len(item["description"]) <= 12
            or any(mark in item["description"] for mark in "|\n\r")
        ):
            raise ValueError(
                "Each fruit list entry needs its own spoken label and description"
            )
    return {
        "policy": "original_fruit_list_word_entries",
        "engine_sha256": _FRUIT_LIST_ENGINE,
        "fixed_title": "水果介绍",
        "background": "original_solid_mode",
        "frames": frames,
        "entry_seconds": starts,
        "assets": media,
        "timing_review": "unreviewed",
    }


def compile_card_clock(
    package: Path,
    group: dict,
    template: dict,
    config: dict,
    native: dict,
    *,
    word_entry: bool = False,
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
        if word_entry:
            # The pinned tracks' second pose is off canvas and their third
            # pose is inside. Keep the prior sampled frame outside.
            outside = f"/cards/{i}/keys/1/0"
            entry = f"/cards/{i}/keys/2/0"
            translated[outside] = max(translated[outside], translated[entry] - 1)
    return translated, {
        "policy": "shared_original_card_clock",
        "engine_sha256": CARD_ENGINE_SHA,
        "template_sha256": CARD_TEMPLATE_SHA,
        "original_landmark_frames": original,
        "current_landmark_frames": current,
        "pose_geometry_preserved": True,
        **({"first_visible_frame_at_word": True} if word_entry else {}),
        "timing_review": "unreviewed",
    }
