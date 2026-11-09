"""Admission and sound clocks for the original YYP presenter compositions."""

import math
from typing import Any

from .video_editing_contracts import Transcript
from .video_editing_materials import PREFIX

PRESENTER_MOTION_GROUPS: dict[str, tuple[str, str | int, str | int]] = {
    "YYP01": ("在实录重点处用原人物窗推近。", "start_frame", "end_frame"),
    "YYP02": ("在实录转折处缩小同期人物，留出背景空间。", "start_frame", "end_frame"),
    "YYP03": ("用原生分区呈现同期人物和手势。", 34, 42),
    "YYP04": ("用原生抠像和描边强调同期人物。", 26, 32),
    "YYP05": ("两段本期补充视频依次进入，口播保留在原圆窗。", 32, 47),
    "YYP06": (
        "用原生运镜带出人物越过窗框的动作。",
        "camera_start_frame",
        "camera_end_frame",
    ),
    "YYP07": ("在实际转折时用原生透视折叠回到同期人物。", 46, 60),
}
MOTION_PRESENTER = "/media/presenter/path"
MOTION_CLIPS = ("/media/broll1/path", "/media/broll2/path")
MOTION_CAPTION = "/content/caption"
MOTION_CLOCK = "/events/caption_frame"
MOTION_GEOMETRY = "/style/geometry/"
MOTION_REVEAL = ("reveal_start_frame", "reveal_end_frame")
MOTION_COMPOSITOR_SHA256 = (
    "ec5115f41bbb44c034bccc66b06169f92a389d4a270eea8c6c6cd1d2e3472038"
)
MOTION_FONT = "font-aa4560dd8fe56457"
MOTION_MATTE = "model-01eb6a29a5c4d8edb30b"
_TAIL_FRAMES = 8
_CLIP_ENTRIES = (32, 40)
_FIXED_SHIFT = -5
_SENTENCE_END = "，。！？；、,.!?;"


def motion_event_paths(group: str) -> tuple[str, ...]:
    _, start, end = PRESENTER_MOTION_GROUPS[group]
    if isinstance(start, int):
        return (MOTION_CLOCK,)
    assert isinstance(end, str)
    paths = (start, end, *MOTION_REVEAL) if group == "YYP06" else (start, end)
    return (*(MOTION_GEOMETRY + key for key in paths), MOTION_CLOCK)


def motion_sound_paths(group: str) -> tuple[str, ...]:
    paths = motion_event_paths(group)
    return (paths[0], paths[2]) if group == "YYP06" else (paths[0],)


def motion_binding(group: str) -> str:
    _, start, end = PRESENTER_MOTION_GROUPS[group]
    guidance = "presenter 绑定同期原片。口播文字由全片主字幕显示，native_text 留空。"
    if isinstance(start, str):
        names = "、".join(
            path.removeprefix(MOTION_GEOMETRY)
            for path in motion_event_paths(group)[:-1]
        )
        return guidance + (
            f"按原顺序把 {names} 绑定实录词点。"
            "每个动作跨度为六至四十二帧，末动作落定后保留至少八帧。"
            "caption_frame 绑定本段首词，以完成原输入时钟。"
        )
    assert isinstance(end, int)
    guidance += (
        "caption_frame 仅记录实际强调词首词，"
        f"须位于镜头内第 {start + _FIXED_SHIFT} 至 {end + _FIXED_SHIFT} 帧。"
    )
    if group == "YYP05":
        guidance += "broll1 和 broll2 各绑定一份不同的本期视频，从各自首帧开始播放。"
    return guidance + "为原动作落定后保留至少八帧。"


def motion_project_clips(cards: list[dict], source_sha: str) -> dict[str, dict]:
    return {
        row["id"]: row
        for row in cards
        if row["kind"] == "video"
        and row["id"].startswith(PREFIX)
        and row["sha256"] != source_sha
        and type(row.get("duration_ms")) is int
    }


def motion_blockers(
    template: dict | None,
    source_subtitles: str,
    cards: list[dict],
    source_sha: str,
    unavailable: dict[str, list[str]],
) -> None:
    groups = {slot["group_id"] for slot in (template or {}).get("slots", [])}
    for group in sorted(groups & PRESENTER_MOTION_GROUPS.keys()):
        if source_subtitles != "none":
            unavailable.setdefault(group, []).append("clean_source_required")
    if "YYP05" not in groups:
        return
    clips = motion_project_clips(cards, source_sha)
    end = PRESENTER_MOTION_GROUPS["YYP05"][2]
    assert isinstance(end, int)
    if not _dual_clip_options(clips, end + _FIXED_SHIFT + _TAIL_FRAMES, _FIXED_SHIFT):
        unavailable.setdefault("YYP05", []).append(
            "two_distinct_project_clips_required"
        )


def _dual_clip_options(
    clips: dict[str, dict], frames: int, shift: int
) -> dict[str, list[str]]:
    options = {
        path: sorted(
            key
            for key, asset in clips.items()
            if asset["duration_ms"] >= math.ceil((frames - shift - entry) * 1000 / 30)
        )
        for path, entry in zip(MOTION_CLIPS, _CLIP_ENTRIES, strict=True)
    }
    left, right = (options[path] for path in MOTION_CLIPS)
    return (
        options
        if any(clips[a]["sha256"] != clips[b]["sha256"] for a in left for b in right)
        else {}
    )


def motion_word_windows(
    template: dict | None,
    transcript: Transcript,
    cards: list[dict],
    unavailable: dict[str, list[str]],
) -> dict[str, list[dict[str, Any]]]:
    """Offer measured, natural clause ranges without sending any timestamps."""
    groups = {slot["group_id"] for slot in (template or {}).get("slots", [])}
    groups = (groups & PRESENTER_MOTION_GROUPS.keys()) - unavailable.keys()
    if not groups or not transcript.tokens:
        return {}
    tokens = transcript.tokens
    cuts = [0]
    cuts.extend(
        i
        for i in range(1, len(tokens))
        if tokens[i - 1].text.rstrip().endswith(tuple(_SENTENCE_END))
        or tokens[i].start_ms - tokens[i - 1].end_ms >= 250
    )
    cuts.append(len(tokens))
    clips = motion_project_clips(cards, transcript.source_sha256)
    windows: dict[str, list[dict[str, Any]]] = {group: [] for group in sorted(groups)}
    for index, first in enumerate(cuts[:-1]):
        start_ms = tokens[first].start_ms
        for stop in cuts[index + 1 : index + 4]:
            duration_ms = tokens[stop - 1].end_ms - start_ms
            if duration_ms > 6500:
                break
            frames = math.ceil(duration_ms * 30 / 1000)
            ticks = [
                (token.id, round((token.start_ms - start_ms) * 30 / 1000))
                for token in tokens[first:stop]
            ]
            for group, options in windows.items():
                _, start, end = PRESENTER_MOTION_GROUPS[group]
                media = {}
                if group == "YYP05":
                    media = _dual_clip_options(clips, frames, _FIXED_SHIFT)
                    if not media:
                        continue
                if isinstance(start, int):
                    assert isinstance(end, int)
                    if frames < end + _FIXED_SHIFT + _TAIL_FRAMES:
                        continue
                    available = [
                        token
                        for token, frame in ticks
                        if start + _FIXED_SHIFT <= frame <= end + _FIXED_SHIFT
                    ]
                    if not available:
                        continue
                    events = {MOTION_CLOCK: available}
                else:
                    events = _motion_geometry_example(group, ticks, frames)
                    if not events:
                        continue
                options.append(
                    {
                        "first_token_id": tokens[first].id,
                        "last_token_id": tokens[stop - 1].id,
                        "start_edge_token_ids": events,
                        **({"project_video_ids_by_path": media} if media else {}),
                    }
                )
    return {
        group: [options[i * (len(options) - 1) // 11] for i in range(12)]
        if len(options) > 12
        else options
        for group, options in windows.items()
    }


def _motion_geometry_example(
    group: str, ticks: list[tuple[str, int]], frames: int
) -> dict[str, list[str]]:
    paths = motion_event_paths(group)[:-1]
    picked: list[str] = []
    pos = 0
    for _ in range(len(paths) // 2):
        pair = next(
            (
                (left, right)
                for left, frame in ticks[pos:]
                for right, close in ticks[pos:]
                if 6 <= close - frame <= 42 and close + _TAIL_FRAMES <= frames
            ),
            None,
        )
        if pair is None:
            return {}
        picked.extend(pair)
        pos = next(i for i, (token, _) in enumerate(ticks) if token == pair[1]) + 1
    return {
        **{path: [token] for path, token in zip(paths, picked, strict=True)},
        MOTION_CLOCK: [ticks[0][0]],
    }


def validate_motion_anchors(
    group: str, anchors: dict, config: dict, clips: dict
) -> None:
    clock = anchors["clock"]
    frames = math.ceil((clock["end_ms"] - clock["start_ms"]) * 30 / 1000)
    by_path = {row["path"]: row for row in anchors["events"]}
    required = motion_event_paths(group)
    if set(by_path) != set(required) or anchors["text"]:
        raise ValueError("Original camera motion needs its measured action clocks")
    events = [by_path[path] for path in required]
    _, start, end = PRESENTER_MOTION_GROUPS[group]
    if isinstance(start, int):
        assert isinstance(end, int)
        shift = config["events"]["shift_frames"]
        event = events[0]
        if not (
            event["edge"] == "start"
            and start + shift <= event["value"] <= end + shift
            and end + shift + _TAIL_FRAMES <= frames
        ):
            raise ValueError("Spoken term misses the original fixed motion window")
        if group == "YYP05":
            selected = {row["path"]: row["asset_id"] for row in anchors["media"]}
            left, right = (clips[selected[path]] for path in MOTION_CLIPS)
            options = _dual_clip_options(clips, frames, shift)
            if left["sha256"] == right["sha256"] or any(
                selected[path] not in options.get(path, []) for path in MOTION_CLIPS
            ):
                raise ValueError(
                    "Original dual composition needs two long enough clips"
                )
        return
    caption = events.pop()
    if caption["edge"] != "start" or caption["measured_anchor_ms"] != clock["start_ms"]:
        raise ValueError("Original camera caption clock needs the first spoken word")
    values = [row["value"] for row in events]
    if (
        any(events[index]["edge"] != "start" for index in range(0, len(events), 2))
        or any(
            not 6 <= b - a <= 42 for a, b in zip(values[::2], values[1::2], strict=True)
        )
        or (len(values) == 4 and values[1] > values[2])
        or values[-1] + _TAIL_FRAMES > frames
    ):
        raise ValueError("Original camera and reveal need ordered measured windows")


def motion_entry_frame(shot: dict, fps: int, path: str) -> int:
    group = shot["group_id"]
    if (
        path not in motion_sound_paths(group)
        or fps != 30
        or shot["layer"] != "scene"
        or shot["rect"] != [0, 0, 1, 1]
    ):
        raise ValueError("Original camera sound requires a full-frame native action")
    config = shot["config"]
    _, start, _ = PRESENTER_MOTION_GROUPS[group]
    if isinstance(start, int):
        # At YYP05's boundary, the circle appears before either clip expands.
        local = start + config["events"]["shift_frames"] + (group != "YYP05")
    else:
        local = config["style"]["geometry"][path.removeprefix(MOTION_GEOMETRY)] + 1
    origin = round(shot["start_seconds"] * 1000) * fps
    return max((origin + 999) // 1000, origin // 1000 + local)
