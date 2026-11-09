"""Classify the pinned native SG-S10 backing title after the original review."""

import importlib
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from .motion_library import atomic_json, read_json, sha256
from .video_editing_render_edits import HY_PORTRAIT_INSETS, boxes_intersect

BACKDROP_GROUP = "SG-S10"
_RENDERER = (
    "src/engines/workspace/字幕动效_可编辑库_20261105/SG-S10/render.py",
    "3ebc549e6eefe28a4c0cb35f5b6af79c2ccf4352d2b01cdd0a137eb5b7dfd712",
)
_REVIEW = (
    "commercial_runtime/layout.py",
    "54dd2899595aeb68859d6c5e5e00cfd25a44e43e021df3639edf315d27ee1d88",
)


def verify_inset_layout(root: Path, review: dict) -> dict:
    """Check opaque inset bounds against the native libass subtitle ink."""
    data = read_json(root / "episode.json")
    indices = read_json(root / "inset-layout-intent.json")["shots"]
    if not indices or review.get("status") != "passed":
        raise ValueError("Verified original layout is required for opaque insets")
    width, height = data["output"]["width"], data["output"]["height"]
    ink = review["caption_ink"]
    if len(ink) != len(data["captions"]) or not all(
        row["start"] == caption["start_seconds"]
        and row["end"] == caption["end_seconds"]
        and len(row["box"]) == 4
        for row, caption in zip(ink, data["captions"], strict=True)
    ):
        raise ValueError("The original caption ink does not cover all main captions")
    checks = []
    for i in indices:
        shot = data["shots"][i]
        start, end = shot["start_seconds"], shot["end_seconds"]
        if (
            shot["group_id"] not in HY_PORTRAIT_INSETS
            or shot["layer"] != "overlay"
            or not any(
                region["id"] == "centered-portrait"
                and region["start_seconds"] <= start < end <= region["end_seconds"]
                for region in data["protected_regions"]
            )
        ):
            raise ValueError("Inset needs a declared speaker keepout for its duration")
        x, y, w, h = shot["rect"]
        box = (
            math.floor(x * width),
            math.floor(y * height),
            math.ceil((x + w) * width) + 2,
            math.ceil((y + h) * height) + 2,
        )
        captions = [row for row in ink if row["start"] < end and start < row["end"]]
        if any(boxes_intersect(box, tuple(row["box"])) for row in captions):
            raise ValueError("Opaque native inset overlaps measured main-caption ink")
        checks.append(
            {
                "shot": i,
                "group_id": shot["group_id"],
                "bounds_px": box,
                "caption_events_checked": len(captions),
            }
        )
    return {"status": "passed", "source": "native libass ink", "insets": checks}


def backdrop_role_overlaps(
    data: dict, report: dict, shot_indices: set[int]
) -> list[dict]:
    """Return documented overlaps only when every failed frame is accounted for."""
    if report.get("status") != "failed" or not report.get("errors"):
        return []
    approved = {}
    for check in report["subtitle_checks"]:
        index = check["shot"]
        if index not in shot_indices:
            continue
        shot = data["shots"][index]
        if (
            shot["layer"] != "subtitle"
            or shot["group_id"] != BACKDROP_GROUP
            or check["group_id"] != BACKDROP_GROUP
        ):
            continue
        config = shot["config"]
        fps = config["frame_format"]["fps"]
        front_start = config["events"]["front_start"]
        for overlap in check["role_review"].get("role_collisions", []):
            frame = overlap["frame"]
            seconds = shot["start_seconds"] + frame / fps
            if (
                overlap["roles"] == ["lead", "accent"]
                and front_start < frame < config["frames"]
                and seconds < shot["end_seconds"]
            ):
                approved[index, seconds] = overlap
    classified = []
    for error in report["errors"]:
        overlap = approved.get((error["shot"], error.get("seconds")))
        if error["against"] != "native_roles" or overlap is None:
            return []
        classified.append({**error, **overlap, "group_id": BACKDROP_GROUP})
    return classified


def review_with_backdrop(
    original: Callable[..., dict],
    data: dict,
    root: Path,
    receipts: list[dict] | None,
    shot_indices: set[int],
) -> dict:
    try:
        return original(data, root, receipts)
    except ValueError as error:
        report_path = root / "layout/review.json"
        if (
            not str(error).startswith("Layout collisions: ")
            or not report_path.is_file()
        ):
            raise
        report = read_json(report_path)
        overlaps = backdrop_role_overlaps(data, report, shot_indices)
        if not overlaps:
            raise
        result = {
            **report,
            "status": "passed",
            "errors": [],
            "original_report_sha256": sha256(report_path),
            "intentional_role_overlaps": overlaps,
            "role_overlap_reason": "SG-S10 的前景横句叠在原机制指定的灰色背衬字上。",
        }
        atomic_json(root / "layout/adapter-review.json", result)
        return result


def install_native_backdrop_review(package: Path, root: Path) -> None:
    intent = root / "layout-intent.json"
    if not intent.is_file():
        return
    indices = set(read_json(intent)["sg_s10_backdrop_shots"])
    if not all(
        sha256(package / path) == identity for path, identity in (_RENDERER, _REVIEW)
    ):
        raise ValueError("Pinned original backdrop renderer or review changed")
    sys.path.insert(0, str(package))
    layout = cast(Any, importlib.import_module("commercial_runtime.layout"))
    original = layout.review

    def review(data: dict, instance: Path, receipts: list[dict] | None = None) -> dict:
        return review_with_backdrop(original, data, Path(instance), receipts, indices)

    layout.review = review
