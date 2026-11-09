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
from .video_editing_subtitle_foreground import (
    FOREGROUND_ROLE_REASONS,
    FOREGROUND_ROLE_RENDERERS,
    foreground_role_windows,
)

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
_PROGRESS_ROLE_RENDERERS = {
    "AH-S01": (
        "src/engines/workspace/字幕动效_可编辑库_20261105/AH-S01/render.py",
        "7cc9946cf2c08c5938ef4584bd7c03f6a5b15cc2f34c67f876c2a3717c3073dd",
    ),
    "BG-S01": (
        "src/engines/workspace/字幕动效_可编辑库_20261105/BG-S01/render.py",
        "34e2ef8ddabf34ae19d5b2781dc52529b95a65cf890ab1c3e9362d00c760cd40",
    ),
    "JJ-S07": (
        "src/engines/workspace/字幕动效_可编辑库_20261105/JJ-S07/render.py",
        "72d9760a23c608885af0d16fef8997b56b863600e6cfa7c9747ce48c18e98731",
    ),
    "JJ-S08": (
        "src/engines/workspace/字幕动效_可编辑库_20261105/JJ-S08/render.py",
        "a3146f8e03cf1b3d587a4fd004d54c240347413d5ec99d9ce422d1959aff6019",
    ),
    "SG-S01": (
        "src/engines/workspace/字幕动效_可编辑库_20261105/SG-S01/render.py",
        "940fc34a86e7f24d89a87a74bf5651a60fdab31f79ccf8b2ce337d32a7685063",
    ),
    "SG-S04": (
        "src/engines/workspace/字幕动效_可编辑库_20261105/SG-S04/render.py",
        "9fda50a11d6abf2fc1e7c51e34b0ef75015c732b07fd1704218b8f20b0d3075c",
    ),
    "SG-S07": (
        "src/engines/workspace/字幕动效_可编辑库_20261105/SG-S07/render.py",
        "c8ddd2b750fa39b6115efd62a7a82d7d71c9d95dcc59d1a806a101ed671356e6",
    ),
}
_SG_MECHANISM = (
    "src/engines/workspace/字幕动效_可编辑库_20261105/SG-production/mechanisms.py",
    "48cd8bf1afd634da9fee47a372048f541902112480ad9fce054d825dcc4bcd9f",
)
LAYERED_SUBTITLE_ROLE_GROUPS = frozenset(
    _PROGRESS_ROLE_RENDERERS.keys() | FOREGROUND_ROLE_RENDERERS.keys()
)
_PROGRESS_ROLE_REASONS = {
    "AH-S01": "AH-S01 的白色说明覆盖原生减淡的黄色关键词。",
    "BG-S01": "BG-S01 的两句仅在同基线入场交接期间可短暂相接。",
    "JJ-S07": "JJ-S07 的左右短词仅在原生分开过程中可短暂相接。",
    "JJ-S08": "JJ-S08 的斜排换位保留原生交叉及换位后说明减淡的叠放。",
    "SG-S01": "SG-S01 分身落定后，仅保留主标题与中间说明的少量字缘接触。",
    "SG-S04": "SG-S04 两个白词在折叠合并期间相接，随后与金色前景短暂交叠。",
    "SG-S07": "SG-S07 的两行只在原生上下换位时交叉。",
}


def _progress_role_windows(
    group: str, config: dict
) -> list[tuple[list[str], int, int]]:
    events = config["events"]
    if group == "AH-S01":
        body = events["body_frame"]
        if 0 <= events["retreat_frame"] - body <= 5:
            return [(["keyword", "body"], body, events["clear_frame"])]
    if group == "BG-S01":
        focus = events["focus_frame"]
        return [(["body", "focus"], focus, focus + 7)]
    if group == "JJ-S07":
        start, end = events["split"]
        return [(["left", "right"], start, end)]
    if group == "JJ-S08":
        start, settle = events["settle"]
        swap, _ = events["swap"]
        if swap - settle >= 6:
            pair = ["headline", "detail"]
            return [(pair, start, settle), (pair, swap, config["frames"])]
    if group == "SG-S01":
        start = max(events["split_end"], events["detail_start"])
        return [(["main", "detail"], start, config["frames"])]
    if group == "SG-S04":
        merge, accent, clear = (
            events[key] for key in ("merge_start", "accent_start", "accent_end")
        )
        if 0 < accent - merge < clear - merge <= 32:
            return [
                (["lead_a", "lead_b"], merge, clear),
                (["lead_a", "accent"], accent, clear),
                (["lead_b", "accent"], accent, clear),
            ]
    if group == "SG-S07":
        return [(["lead", "accent"], events["swap_start"], events["swap_end"])]
    return []


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


def verified_effect_groups(episode: dict, delivery: dict) -> set[str]:
    """Count visible native effects using the actual original export receipts."""
    shots, receipts = episode["shots"], delivery["shots"]
    layout = delivery["layout_review"]
    if (
        layout["status"] != "passed"
        or delivery["review"]["encoded_full_decode"] is not True
        or len(shots) != len(receipts)
    ):
        raise ValueError("The original composition and layout are required")
    checks = {row["shot"]: row for row in layout["subtitle_checks"]}
    if len(checks) != len(layout["subtitle_checks"]) or any(
        not 0 <= index < len(shots) for index in checks
    ):
        raise ValueError("Native alpha checks must identify one existing shot each")

    fps = episode["output"]["fps"]
    visible = set()
    for index, (shot, receipt) in enumerate(zip(shots, receipts, strict=True)):
        group = shot["group_id"]
        if (
            receipt["group_id"] != group
            or receipt["decoded"] is not True
            or receipt["encoding"]["full_decode"] is not True
            or receipt["encoding"]["format"]["frames"] < 1
        ):
            raise ValueError("Native shot encoding does not match the composition")
        if check := checks.get(index):
            if check["group_id"] != group or check["visible_frames"] < 1:
                raise ValueError("Native alpha check found no visible effect")
        elif shot["layer"] == "subtitle":
            raise ValueError("A subtitle needs a native alpha check")
        elif (
            shot["layer"] not in {"scene", "overlay"}
            or receipt.get("rgba_sequence")
            or math.ceil(shot["start_seconds"] * fps - 1e-6)
            >= math.ceil(shot["end_seconds"] * fps - 1e-6)
        ):
            continue
        if group != "Z-M00":
            visible.add(group)
    return visible


def intentional_role_overlaps(
    data: dict,
    report: dict,
    backdrop_shots: set[int],
    question_shots: set[int] | None = None,
    handoff_shots: set[int] | None = None,
    progress_shots: set[int] | None = None,
) -> list[dict]:
    """Return documented overlaps only when every failed frame is accounted for."""
    if report.get("status") != "failed" or not report.get("errors"):
        return []
    approved: dict[tuple[int, float], list[dict]] = {}
    for check in report["subtitle_checks"]:
        index = check["shot"]
        shot = data["shots"][index]
        group_id = shot["group_id"]
        if check["group_id"] != group_id or shot["layer"] != "subtitle":
            continue
        config = shot["config"]
        if index in backdrop_shots and group_id == BACKDROP_GROUP:
            fps = config["frame_format"]["fps"]
            windows = [
                (["lead", "accent"], config["events"]["front_start"], config["frames"])
            ]
        elif (
            question_shots
            and index in question_shots
            and group_id == QUESTION_CARD_GROUP
            and question_card_a_shot(shot)
        ):
            fps = 30
            windows = [
                (
                    ["english", "question"],
                    config["events"]["question_frame"],
                    config["events"]["clear_frame"],
                )
            ]
        elif (
            handoff_shots and index in handoff_shots and group_id == TEXT_HANDOFF_GROUP
        ):
            fps = 30
            enter, clear = config["events"]["handoff"]
            if not 1 <= clear - enter <= TEXT_HANDOFF_MAX_FRAMES:
                continue
            windows = [(["body", "keyword"], enter, clear)]
        elif (
            progress_shots
            and index in progress_shots
            and group_id in LAYERED_SUBTITLE_ROLE_GROUPS
        ):
            fps = 30
            windows = (
                foreground_role_windows(group_id, config)
                if group_id in FOREGROUND_ROLE_RENDERERS
                else _progress_role_windows(group_id, config)
            )
        else:
            continue
        for overlap in check["role_review"].get("role_collisions", []):
            frame = overlap["frame"]
            seconds = shot["start_seconds"] + frame / fps
            if group_id == "SG-S01" and overlap["pixels"] > 64:
                continue
            if (
                any(
                    overlap["roles"] == roles and enter < frame < clear
                    for roles, enter, clear in windows
                )
                and seconds < shot["end_seconds"]
            ):
                approved.setdefault((index, seconds), []).append(
                    {**overlap, "group_id": group_id}
                )
    classified = []
    for error in report["errors"]:
        if error["against"] != "native_roles":
            return []
        matches = approved.get((error["shot"], error["seconds"]))
        if not matches:
            return []
        classified.append({**error, **matches.pop()})
    return classified


def review_with_native_roles(
    original: Callable[..., dict],
    data: dict,
    root: Path,
    receipts: list[dict] | None,
    backdrop_shots: set[int],
    question_shots: set[int] | None = None,
    handoff_shots: set[int] | None = None,
    progress_shots: set[int] | None = None,
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
            data, report, backdrop_shots, question_shots, handoff_shots, progress_shots
        )
        if not overlaps:
            raise
        groups = {row["group_id"] for row in overlaps}
        reasons = {
            BACKDROP_GROUP: "SG-S10 的前景横句叠在原机制指定的灰色背衬字上。",
            QUESTION_CARD_GROUP: "原 AH-S03 A 版问号覆盖英文释义。",
            TEXT_HANDOFF_GROUP: "JJ-S06 仅在原生同位置淡入淡出交接期间叠放。",
            **_PROGRESS_ROLE_REASONS,
            **FOREGROUND_ROLE_REASONS,
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
    progress = set(spec.get("progress_role_shots", []))
    pinned = [_REVIEW]
    if backdrop:
        pinned.append(_RENDERER)
    if question:
        pinned.append(_QUESTION_RENDERER)
    if handoff:
        pinned.append(_HANDOFF_RENDERER)
    if progress:
        shots = read_json(root / "episode.json")["shots"]
        groups = {shots[index]["group_id"] for index in progress}
        for group in groups:
            if group in FOREGROUND_ROLE_RENDERERS:
                pinned.extend(FOREGROUND_ROLE_RENDERERS[group])
            else:
                pinned.append(_PROGRESS_ROLE_RENDERERS[group])
        if groups & {"SG-S04", "SG-S07"}:
            pinned.append(_SG_MECHANISM)
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
            original,
            data,
            Path(instance),
            receipts,
            backdrop,
            question,
            handoff,
            progress,
        )

    layout.review = review
