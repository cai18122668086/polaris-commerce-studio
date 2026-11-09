"""Preserve intentional original role overlaps after running the native review."""

import importlib
import math
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from .motion_library import atomic_json, read_json, sha256
from .video_editing_browser_clocks import NUMBERED_GROUP
from .video_editing_browser_live import CARD_LIVE_PREFIX
from .video_editing_question_card import QUESTION_CARD_GROUP, question_card_a_shot
from .video_editing_render_edits import NATIVE_PORTRAIT_INSETS, boxes_intersect

BACKDROP_GROUP = "SG-S10"
TEXT_HANDOFF_GROUP = "JJ-S06"
TEXT_HANDOFF_MAX_FRAMES = 12
_RENDERER = (
    "src/engines/workspace/字幕动效_可编辑库_20261105/SG-S10/render.py",
    "3ebc549e6eefe28a4c0cb35f5b6af79c2ccf4352d2b01cdd0a137eb5b7dfd712",
)
_QUESTION_RENDERER = (
    "src/engines/workspace/字幕动效_可编辑库_20261105/AH-S03/render.py",
    "1aa9c7d92ab7e203fabd482d2cbf459f0eb349699aa1f0421571424387ba229d",
)
_HANDOFF_RENDERER = (
    "src/engines/workspace/字幕动效_可编辑库_20261105/JJ-S06/render.py",
    "0c636349453a5f707316445aa84565c05c57bfdfaa8f63fab5b7b0a847aeae90",
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
            shot["group_id"] not in NATIVE_PORTRAIT_INSETS
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


def intentional_role_overlaps(
    data: dict,
    report: dict,
    backdrop_shots: set[int],
    question_shots: set[int] | None = None,
    handoff_shots: set[int] | None = None,
) -> list[dict]:
    """Return documented overlaps only when every failed frame is accounted for."""
    if report.get("status") != "failed" or not report.get("errors"):
        return []
    approved = {}
    for check in report["subtitle_checks"]:
        index = check["shot"]
        shot = data["shots"][index]
        group_id = shot["group_id"]
        if check["group_id"] != group_id or shot["layer"] != "subtitle":
            continue
        config = shot["config"]
        if index in backdrop_shots and group_id == BACKDROP_GROUP:
            fps = config["frame_format"]["fps"]
            enter, clear = config["events"]["front_start"], config["frames"]
            roles = ["lead", "accent"]
        elif (
            question_shots
            and index in question_shots
            and group_id == QUESTION_CARD_GROUP
            and question_card_a_shot(shot)
        ):
            fps = 30
            enter, clear = (
                config["events"]["question_frame"],
                config["events"]["clear_frame"],
            )
            roles = ["english", "question"]
        elif (
            handoff_shots and index in handoff_shots and group_id == TEXT_HANDOFF_GROUP
        ):
            fps = 30
            enter, clear = config["events"]["handoff"]
            if not 1 <= clear - enter <= TEXT_HANDOFF_MAX_FRAMES:
                continue
            roles = ["body", "keyword"]
        else:
            continue
        for overlap in check["role_review"].get("role_collisions", []):
            frame = overlap["frame"]
            seconds = shot["start_seconds"] + frame / fps
            if (
                overlap["roles"] == roles
                and enter < frame < clear
                and seconds < shot["end_seconds"]
            ):
                approved[index, seconds] = {**overlap, "group_id": group_id}
    classified = []
    for error in report["errors"]:
        overlap = approved.get((error["shot"], error.get("seconds")))
        if error["against"] != "native_roles" or overlap is None:
            return []
        classified.append({**error, **overlap})
    return classified


def review_with_native_roles(
    original: Callable[..., dict],
    data: dict,
    root: Path,
    receipts: list[dict] | None,
    backdrop_shots: set[int],
    question_shots: set[int] | None = None,
    handoff_shots: set[int] | None = None,
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
        overlaps = intentional_role_overlaps(
            data, report, backdrop_shots, question_shots, handoff_shots
        )
        if not overlaps:
            raise
        groups = {row["group_id"] for row in overlaps}
        reasons = {
            BACKDROP_GROUP: "SG-S10 的前景横句叠在原机制指定的灰色背衬字上。",
            QUESTION_CARD_GROUP: "原 AH-S03 A 版问号覆盖英文释义。",
            TEXT_HANDOFF_GROUP: "JJ-S06 仅在原生同位置淡入淡出交接期间叠放。",
        }
        result = {
            **report,
            "status": "passed",
            "errors": [],
            "original_report_sha256": sha256(report_path),
            "intentional_role_overlaps": overlaps,
            "role_overlap_reason": "".join(reasons[group] for group in sorted(groups)),
        }
        atomic_json(root / "layout/adapter-review.json", result)
        return result


def install_native_role_review(package: Path, root: Path) -> None:
    intent = root / "layout-intent.json"
    if not intent.is_file():
        return
    spec = read_json(intent)
    backdrop = set(spec.get("sg_s10_backdrop_shots", []))
    question = set(spec.get("ah_s03_input_a_shots", []))
    numbered = set(spec.get("numbered_alpha_shots", []))
    handoff = set(spec.get("jj_s06_handoff_shots", []))
    pinned = [_REVIEW]
    if backdrop:
        pinned.append(_RENDERER)
    if question:
        pinned.append(_QUESTION_RENDERER)
    if handoff:
        pinned.append(_HANDOFF_RENDERER)
    if not all(sha256(package / path) == identity for path, identity in pinned):
        raise ValueError("Pinned original role renderer or review changed")
    sys.path.insert(0, str(package))
    layout = cast(Any, importlib.import_module("commercial_runtime.layout"))
    original = layout.review

    def review(data: dict, instance: Path, receipts: list[dict] | None = None) -> dict:
        if numbered:
            # Use the original subtitle alpha/ink checks for the numbered labels.
            # The exporter still composites the actual shot as a picture overlay.
            shots = list(data["shots"])
            for index in numbered:
                shot = shots[index]
                if (
                    shot["group_id"] != NUMBERED_GROUP
                    or shot["layer"] != "overlay"
                    or shot["rect"] != [0, 0, 1, 1]
                    or not shot["config"]["presenter"].startswith(
                        "input://" + CARD_LIVE_PREFIX
                    )
                ):
                    raise ValueError("Numbered labels need a live alpha overlay")
                shots[index] = {**shot, "layer": "subtitle"}
            data = {**data, "shots": shots}
        return review_with_native_roles(
            original, data, Path(instance), receipts, backdrop, question, handoff
        )

    layout.review = review
