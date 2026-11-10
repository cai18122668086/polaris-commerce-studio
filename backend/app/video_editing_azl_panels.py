"""Preserve the original AZL panels inside the portrait website episode."""

import math
from pathlib import Path

from .motion_library import read_json, sha256
from .video_editing_contracts import Transcript
from .video_editing_materials import PREFIX
from .video_editing_presenter_motion import MOTION_COMPOSITOR_SHA256
from .video_editing_word_bindings import emphasis_text, measured_clause_windows

AZL_GROUPS = {
    "AZL01": ("白底包围式布局，将讲述者与本期实景放在同一板式。", ("main",)),
    "AZL02": ("两个独立实景配合左上同期人物圆窗。", ("main", "secondary")),
    "AZL03": ("上方呈现抠像人物和关键词，下方展示独立实景。", ("secondary",)),
    "AZL04": ("三个独立素材带围绕中央的同期讲述者。", ("main", "secondary", "lower")),
    "AZL05": ("用原生斜线分割讲述者和两路实景。", ("main", "secondary")),
    "AZL06": ("用同一素材的三张透视关键词卡配合同期讲述者。", ("main",)),
    "AZL07": ("用同一补充素材的上下裁片包围同期讲述者。", ("main",)),
}
AZL_DEPENDENCIES = ("font-aa4560dd8fe56457", "model-01eb6a29a5c4d8edb30b")
AZL_TEMPLATE_ID = "azl-panels-v1"
AZL_DESIGN_ID = "tengli-azl-panels-v1"
AZL_PRESENTER = "/media/presenter/path"
AZL_SUBTITLE = "/content/subtitle"
AZL_EVENTS = tuple(
    f"/events/subtitle_{action}/{i}" for action in ("in", "out") for i in range(2)
)
AZL_ENTRY = AZL_EVENTS[0]
AZL_RECT = (0.0, 0.0, 1.0, 27 / 32)
AZL_CAPTION_BASELINE = 1230
AZL_LAYOUT_INTENT = "azl-panel-layout-intent.json"
_MIN_FRAMES = 36
_FRAME_GATE_MARGIN = 1e-5
_BACKING = {
    "AZL01": "#ffffff",
    "AZL03": "#030405",
    "AZL06": "#030405",
    "AZL07": "#000000",
}
_SCENE_COMPOSER_SHA256 = (
    "68625c053059bf7ffd71fc89d3cc33313573b8979ba9a3a8758e501a81f6e913"
)


def azl_slots(group: str) -> tuple[str, ...]:
    return tuple(f"/media/{name}/path" for name in AZL_GROUPS[group][1])


def azl_binding(group: str) -> str:
    slots = "、".join(AZL_GROUPS[group][1])
    return (
        f"presenter 绑定同期原片。{slots} 各绑定不同的本期图片或足够长的视频。"
        "补充视频从各自首帧播放，须覆盖整段。"
        "subtitle 和 subtitle_in/0 都从本段首词开始，取实录短句，"
        "落定后留出阅读时间，最后两个边界用于原生淡出。"
        + (
            "三张关键词卡各取同段中顺序不同的实录短语，背景共用原 main 槽。"
            if group == "AZL06"
            else "title 和 tagline 各取本段实录短语。"
        )
    )


def azl_materials(cards: list[dict], source_sha: str, frames: int) -> dict[str, dict]:
    duration_ms = math.ceil(frames * 1000 / 30)
    return {
        row["id"]: row
        for row in cards
        if row["id"].startswith(PREFIX)
        and row["sha256"] != source_sha
        and (
            row["kind"] == "image"
            or (
                row["kind"] == "video"
                and type(row.get("duration_ms")) is int
                and row["duration_ms"] >= duration_ms
            )
        )
    }


def azl_blockers(
    template: dict | None,
    source_subtitles: str,
    cards: list[dict],
    source_sha: str,
    unavailable: dict[str, list[str]],
) -> None:
    groups = {slot["group_id"] for slot in (template or {}).get("slots", [])}
    scoped = groups & AZL_GROUPS.keys()
    if not scoped:
        return
    count = len(
        {
            row["sha256"]
            for row in azl_materials(cards, source_sha, _MIN_FRAMES).values()
        }
    )
    for group in sorted(scoped):
        if source_subtitles != "none":
            unavailable.setdefault(group, []).append("clean_source_required")
        if count < len(azl_slots(group)):
            unavailable.setdefault(group, []).append(
                "distinct_panel_materials_required"
            )


def azl_panel_windows(
    template: dict | None, transcript: Transcript, cards: list[dict], unavailable: dict
) -> list[dict]:
    if not template or template["id"] != AZL_TEMPLATE_ID:
        return []
    groups = sorted(AZL_GROUPS.keys() - unavailable.keys())
    if not groups:
        return []
    options = []
    for tokens in measured_clause_windows(transcript):
        first = tokens[0]
        frames = math.ceil((tokens[-1].end_ms - first.start_ms) * 30 / 1000)
        if frames < _MIN_FRAMES or len(tokens) < 5:
            continue
        assets = azl_materials(cards, transcript.source_sha256, frames)
        count = len({asset["sha256"] for asset in assets.values()})
        eligible = [group for group in groups if len(azl_slots(group)) <= count]
        if not eligible:
            continue
        prefix = tokens[:3]
        text = emphasis_text(
            "".join(token.text for token in prefix), "omit_sentence_punctuation"
        )
        if not 1 <= len(text) <= 12 or "\n" in text:
            continue
        starts = [
            round((token.start_ms - first.start_ms) * 30 / 1000) for token in tokens
        ]
        ends = [round((token.end_ms - first.start_ms) * 30 / 1000) for token in tokens]
        settle = next((i for i, frame in enumerate(ends) if 0 < frame <= 15), None)
        if settle is None:
            continue
        min_exit = ends[settle] + max(6, math.ceil(len(text) * 30 / 16))
        out = next(
            (
                i
                for i in range(len(prefix) - 1, len(tokens))
                if starts[i] >= min_exit and starts[i] < ends[-1]
            ),
            None,
        )
        if out is None:
            continue
        edges = [
            (first, "start"),
            (tokens[settle], "end"),
            (tokens[out], "start"),
            (tokens[-1], "end"),
        ]
        options.append(
            {
                "first_token_id": first.id,
                "last_token_id": tokens[-1].id,
                "group_ids": eligible,
                "material_ids": sorted(assets),
                "subtitle_last_token_id": prefix[-1].id,
                "native_events": [
                    {"path": path, "token_id": token.id, "edge": edge}
                    for path, (token, edge) in zip(AZL_EVENTS, edges, strict=True)
                ],
            }
        )
    if len(options) > 18:
        return [options[index * (len(options) - 1) // 17] for index in range(18)]
    return options


def validate_azl_anchors(
    group: str, anchors: dict, capacity: dict, token_positions: dict[str, int]
) -> None:
    text = {row["path"]: row for row in anchors["text"]}
    events = {row["path"]: row for row in anchors["events"]}
    if set(events) != set(AZL_EVENTS):
        raise ValueError("Original panel needs all four subtitle boundaries")
    for path, row in text.items():
        role = path.split("/")[2]
        limit = 7 if role == "title" and group in {"AZL02", "AZL03"} else capacity[role]
        if not 1 <= len(row["text"]) <= limit or "\n" in row["text"]:
            raise ValueError("Spoken text exceeds the original panel role capacity")
    if group == "AZL06":
        cards = [text[f"/content/cards/{index}"]["token_ids"] for index in range(3)]
        if any(
            token_positions[left[-1]] >= token_positions[right[0]]
            for left, right in zip(cards, cards[1:], strict=False)
        ):
            raise ValueError(
                "Original keyword cards need three distinct spoken items in order"
            )
    entry, settle, exit_start, exit_end = (events[path]["value"] for path in AZL_EVENTS)
    clock = anchors["clock"]
    frames = math.ceil((clock["end_ms"] - clock["start_ms"]) * 30 / 1000)
    subtitle = text[AZL_SUBTITLE]
    if not (
        frames >= _MIN_FRAMES
        and entry == 0 < settle <= 15
        and events[AZL_ENTRY]["edge"] == "start"
        and events[AZL_ENTRY]["measured_anchor_ms"] == clock["start_ms"]
        and events[AZL_ENTRY]["token_id"] == subtitle["token_ids"][0]
        and settle + max(6, math.ceil(len(subtitle["text"]) * 30 / 16)) <= exit_start
        and token_positions[events[AZL_EVENTS[2]]["token_id"]]
        >= token_positions[subtitle["token_ids"][-1]]
        and exit_start < exit_end <= frames
    ):
        raise ValueError(
            "Original panel subtitle must begin with the scene and leave reading time"
        )


def azl_output_bounds(shot: dict, fps: int) -> tuple[int, int]:
    if (
        fps != 30
        or shot["group_id"] not in AZL_GROUPS
        or shot["layer"] != "scene"
        or tuple(shot["rect"]) != AZL_RECT
        or shot["config"]["events"]["subtitle_in"][0] != 0
    ):
        raise ValueError("Expected the original portrait-adapted AZL panel")
    return tuple(
        math.ceil(shot[key] * fps - 1e-6) for key in ("start_seconds", "end_seconds")
    )


def azl_backing(shot: dict, episode: dict, index: int) -> dict:
    fmt = episode["output"]
    fps = fmt["fps"]
    if fmt["height"] * AZL_RECT[3] != fmt["width"] * 1.5:
        raise ValueError("Original AZL board needs an uncropped 2:3 projection")
    first, end = azl_output_bounds(shot, fps)
    duration = episode["source"]["duration_seconds"]
    return {
        "id": f"azl-backing-{index}",
        "start_seconds": first / fps,
        # End before FFmpeg's floating-point representation of the excluded frame.
        "end_seconds": min((end - _FRAME_GATE_MARGIN) / fps, duration),
        "background": {
            "mode": "solid",
            "color": _BACKING.get(shot["group_id"], "#050607"),
        },
        "layers": [],
    }


def require_azl_compositor(package: Path) -> None:
    native = package / "commercial_runtime"
    if (
        sha256(native / "scene_composer.py") != _SCENE_COMPOSER_SHA256
        or sha256(native / "episode.py") != MOTION_COMPOSITOR_SHA256
    ):
        raise ValueError("Original AZL backing or composition clock changed")


def verify_azl_layout(root: Path, delivery: dict) -> dict:
    episode = read_json(root / "episode.json")
    indices = read_json(root / AZL_LAYOUT_INTENT)["shots"]
    layout = delivery["layout_review"]
    ink, captions = layout["caption_ink"], episode["captions"]
    if (
        not indices
        or layout["status"] != "passed"
        or len(ink) != len(captions)
        or any(
            (row["start"], row["end"])
            != (caption["start_seconds"], caption["end_seconds"])
            or len(row["box"]) != 4
            for row, caption in zip(ink, captions, strict=True)
        )
    ):
        raise ValueError("AZL main subtitle ink must match the original layout")
    bottom = round(episode["output"]["height"] * AZL_RECT[3])
    receipts = {row["scene_id"]: row for row in delivery["visual_scene_receipts"]}
    expected = []
    checks = []
    for index in indices:
        shot = episode["shots"][index]
        backing = azl_backing(shot, episode, index)
        expected.append(backing)
        receipt = receipts[backing["id"]]
        fps = episode["output"]["fps"]
        first, end = azl_output_bounds(shot, fps)
        end = min(end, round(episode["source"]["duration_seconds"] * fps))
        if (
            receipt["frames"] != end - first
            or receipt["fps"] != fps
            or receipt["layer_kinds"]
        ):
            raise ValueError(
                "Original AZL solid backing does not cover the panel frames"
            )
        active = [
            row
            for row in ink
            if row["start"] < shot["end_seconds"] and shot["start_seconds"] < row["end"]
        ]
        if not active or min(row["box"][1] for row in active) < bottom:
            raise ValueError("Main subtitle ink enters the original AZL panel")
        checks.append(
            {
                "group_id": shot["group_id"],
                "first_frame": first,
                "last_frame": end - 1,
                "smallest_caption_gap_px": min(row["box"][1] for row in active)
                - bottom,
            }
        )
    if episode["visual_scenes"] != expected or len(receipts) != len(indices):
        raise ValueError("Original AZL backing plan differs from its rendered receipt")
    return {"status": "passed", "panel_bottom_px": bottom, "shots": checks}
