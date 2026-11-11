"""Readable display clocks and a reserved caption lane for website templates.

Word anchors, native event times and the narration are preserved. Display holds
and scene tail extensions are explicit presentation decisions, never ASR times.
The original scene is contained, with its aspect ratio intact, above the lane.
"""

import copy
import math
import re
from pathlib import Path

from .motion_library import read_json
from .video_editing_captioning import CaptionFailure, measured_caption_rows
from .video_editing_contracts import Transcript

POLICY = "tengli.caption-presentation/1"
KEY = "caption_presentation"
MAX_DISPLAY_GAP = 0.8


def readable_caption_rows(transcript: Transcript) -> list[dict]:
    try:
        rows = measured_caption_rows(transcript, max_chars=12)
    except CaptionFailure as error:
        if error.code != "EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED":
            raise
        # An indivisible measured token can require the original two-line layout.
        rows = measured_caption_rows(transcript)
    merged: list[dict] = []
    for row in rows:
        previous = merged[-1] if merged else None
        if (
            previous
            and len(previous["text"] + row["text"]) <= 12
            and len(previous["text"]) < 6
            and not re.search(r"[。！？!?；;][”’\"']?$", previous["text"])
            and row["start_seconds"] - previous["end_seconds"] <= MAX_DISPLAY_GAP
            and row["end_seconds"] - previous["start_seconds"] <= 3.5
        ):
            previous.update(
                text=previous["text"] + row["text"],
                end_seconds=row["end_seconds"],
                token_ids=previous["token_ids"] + row["token_ids"],
            )
        else:
            merged.append(copy.deepcopy(row))
    for i, row in enumerate(merged):
        row["speech_end_seconds"] = row["end_seconds"]
        following = (
            merged[i + 1]["start_seconds"]
            if i + 1 < len(merged)
            else transcript.duration_ms / 1000
        )
        gap = following - row["end_seconds"]
        row["end_seconds"] = (
            following
            if 0 <= gap <= MAX_DISPLAY_GAP and i + 1 < len(merged)
            else min(following, row["end_seconds"] + 0.2)
        )
    return merged


def _plain(text: str) -> str:
    return re.sub(r"[^\w]", "", text)


def remove_duplicate_captions(episode: dict, anchors: list[dict]) -> list[dict]:
    """Only a native complete spoken caption can replace the ordinary caption."""
    removed = []
    captions = episode["captions"]
    for shot in episode["shots"]:
        if shot["group_id"] not in {"LYO01", "LYO04"}:
            continue
        native = shot["config"].get("content", {}).get("caption", "")
        covered = [
            row
            for row in anchors
            if shot["start_seconds"] <= row["start_seconds"]
            and row.get("speech_end_seconds", row["end_seconds"])
            <= shot["end_seconds"] + 0.001
        ]
        if not covered or _plain(native) != _plain("".join(r["text"] for r in covered)):
            continue
        # Keep the main text until the native caption actually enters.
        config = shot["config"]
        event = config.get("events", {}).get("text_frame")
        if not isinstance(event, (int, float)):
            continue
        visible = shot["start_seconds"] + max(0, event) / 30
        intervals = [(visible, shot["end_seconds"])]
        output = []
        for row in captions:
            for start, end in intervals:
                if row["start_seconds"] < end and start < row["end_seconds"]:
                    if row["start_seconds"] < start:
                        output.append({**row, "end_seconds": start})
                    if end < row["end_seconds"]:
                        output.append({**row, "start_seconds": end})
                    removed.append(
                        {
                            "group_id": shot["group_id"],
                            "text": row["text"],
                            "start_seconds": max(start, row["start_seconds"]),
                            "end_seconds": min(end, row["end_seconds"]),
                        }
                    )
                else:
                    output.append(row)
        captions = output
    episode["captions"] = captions
    return removed


def bridge_scene_gaps(episode: dict, bindings: dict | None = None) -> list[dict]:
    changes = []
    shots = episode["shots"]
    resources = (bindings or {}).get("resources", {})
    families = [
        {"Z-M15"},
        {"AZL01", "AZL02", "AZL03", "AZL04", "AZL05", "AZL06", "AZL07"},
    ]
    for shot, following in zip(shots, shots[1:], strict=False):
        gap = following["start_seconds"] - shot["end_seconds"]
        if (
            not 1 / 30 < gap <= MAX_DISPLAY_GAP
            or shot.get("layer") != "scene"
            or following.get("layer") != "scene"
            or not any(
                shot["group_id"] in family and following["group_id"] in family
                for family in families
            )
        ):
            continue
        config = shot["config"]
        media = config.get("media", {})
        # These two families bind the continuing presenter plus still pictures.
        supplements = [item for name, item in media.items() if name != "presenter"]
        if any(
            not isinstance(item, dict)
            or (
                item.get("kind") != "image"
                and Path(
                    resources.get(item.get("path", "").removeprefix("input://"), "")
                ).suffix.lower()
                not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}
            )
            for item in supplements
        ):
            continue
        old_end = shot["end_seconds"]
        end = following["start_seconds"]
        frames = math.ceil(end * 30 - 1e-6) - math.floor(
            shot["start_seconds"] * 30 + 1e-6
        )
        duration = frames / 30
        presenter = media.get("presenter", {})
        if "offset_seconds" not in presenter or "duration_seconds" not in presenter:
            continue
        if (
            presenter.get("offset_seconds", 0) + duration
            > episode["source"]["duration_seconds"]
        ):
            continue
        if "frames" in config:
            config["frames"] = frames
        elif "timing" in config:
            config["timing"]["duration_seconds"] = duration
        else:
            continue
        presenter["duration_seconds"] = duration
        shot["end_seconds"] = end
        changes.append(
            {
                "group_id": shot["group_id"],
                "old_end_seconds": old_end,
                "end_seconds": end,
                "source_clock_continues": True,
            }
        )
    return changes


def reserve_caption_lane(
    episode: dict, removed: list[dict], bridges: list[dict]
) -> dict:
    role = episode["typography"]["caption"]
    height = episode["output"]["height"]
    baseline = round(height * 0.84)
    role["center_x_px"] = episode["output"]["width"] / 2
    role["baseline_y_px"] = baseline
    role.pop("layout_overrides", None)
    lines = max((row["text"].count("\n") + 1 for row in episode["captions"]), default=1)
    area = (
        math.floor((baseline - role["size_px"] * lines - 0.025 * height) / 2)
        * 2
        / height
    )
    scenes = []
    backings = []
    fps = episode["output"]["fps"]
    for index, shot in enumerate(episode["shots"]):
        if shot.get("layer") != "scene" or shot["group_id"] == "Z-M00":
            continue
        if not any(
            row["start_seconds"] < shot["end_seconds"]
            and shot["start_seconds"] < row["end_seconds"]
            for row in episode["captions"]
        ):
            # A native complete caption already owns this shot. Preserve its
            # original full-frame composition rather than leaving an empty lane.
            continue
        original = list(shot["rect"])
        factor = min(1, area / (original[1] + original[3]))
        rect = [original[0], original[1] * factor, original[2], original[3] * factor]
        shot["rect"] = rect
        scenes.append({"shot_index": index, "original_rect": original, "rect": rect})
        if not shot["group_id"].startswith("AZL"):
            first = math.ceil(shot["start_seconds"] * fps - 1e-6)
            end = math.ceil(shot["end_seconds"] * fps - 1e-6)
            backings.append(
                {
                    "id": f"caption-backing-{index}",
                    "start_seconds": first / fps,
                    "end_seconds": min(
                        (end - 1e-5) / fps, episode["source"]["duration_seconds"]
                    ),
                    "background": {"mode": "solid", "color": "#050607"},
                    "layers": [],
                }
            )
    episode["visual_scenes"].extend(backings)
    # A scene can be larger than its native 2:3 panel, but is always contained.
    report = {
        "policy": POLICY,
        "baseline_y_px": baseline,
        "scene_area_bottom_ratio": area,
        "scenes": scenes,
        "native_caption_replacements": removed,
        "scene_bridges": bridges,
        "narration_changed": False,
        "word_timestamps_changed": False,
    }
    episode["editorial"][KEY] = report
    return report


def register_caption_backings(episode: dict, selection: dict) -> None:
    registered = {row.get("scene_id") for row in selection["decisions"]}
    for scene in episode["visual_scenes"]:
        if scene["id"].startswith("caption-backing-") and scene["id"] not in registered:
            index = int(scene["id"].rsplit("-", 1)[1])
            selection["decisions"].append(
                {
                    "scene_id": scene["id"],
                    "viewer_task": "稳定阅读连续口播主字幕。",
                    "reason": "保留原生构图比例，在画面下方预留独立字幕读区。",
                    "considered": [{"group_id": episode["shots"][index]["group_id"]}],
                }
            )


def native_clock_shot(episode: dict, index: int) -> dict:
    """Native animation events retain their original local pixel/frame clock."""
    shot = episode["shots"][index]
    presentation = episode.get("editorial", {}).get(KEY, {})
    for row in presentation.get("scenes", []):
        if row["shot_index"] == index:
            if shot["rect"] != row["rect"]:
                raise ValueError("Contained scene differs from its native clock view")
            return {**shot, "rect": row["original_rect"]}
    return shot


def verify_reserved_caption_lane(
    root: Path, report: dict, indices: list[int]
) -> dict | None:
    episode = read_json(root / "episode.json")
    presentation = episode.get("editorial", {}).get(KEY)
    if not presentation:
        return None
    if presentation.get("policy") != POLICY or report.get("status") != "passed":
        raise ValueError("Caption presentation requires the verified native layout")
    captions = episode["captions"]
    ink = report["caption_ink"]
    height = episode["output"]["height"]
    role = episode["typography"]["caption"]
    if (
        role["baseline_y_px"] != round(height * 0.84)
        or role.get("layout_overrides")
        or presentation["baseline_y_px"] != role["baseline_y_px"]
    ):
        raise ValueError("Main captions must use the stable reading baseline")
    if len(ink) != len(captions) or any(
        (a["start"], a["end"]) != (b["start_seconds"], b["end_seconds"])
        for a, b in zip(ink, captions, strict=True)
    ):
        raise ValueError("Caption ink differs from the current display clock")
    if any(row["box"][3] > math.floor(height * 0.88) for row in ink):
        raise ValueError("Main caption ink enters the lower platform margin")
    scenes = {row["shot_index"]: row for row in presentation["scenes"]}
    for index in indices:
        shot = episode["shots"][index]
        expected = scenes[index]
        area = presentation["scene_area_bottom_ratio"]
        original = expected["original_rect"]
        factor = min(1, area / (original[1] + original[3]))
        rect = [original[0], original[1] * factor, original[2], original[3] * factor]
        if shot["rect"] != rect or rect != expected["rect"]:
            raise ValueError("The reserved scene viewport changed")
        bottom = (rect[1] + rect[3]) * height
        for row in ink:
            if (
                row["start"] < shot["end_seconds"]
                and shot["start_seconds"] < row["end"]
                and row["box"][1] < bottom
            ):
                raise ValueError("Main caption ink overlaps the contained native scene")
    return {"status": "passed", "policy": POLICY, "shots_checked": len(indices)}
