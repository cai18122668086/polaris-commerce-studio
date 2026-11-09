"""Word timing and caption clearance for six original YYO opening scenes."""

import math
from pathlib import Path

from .motion_library import read_json
from .video_editing_contracts import Transcript

YY_OPENING_GROUPS = {
    "YYO01": "从缩小的人物画面展开，保留原生放大及标题。",
    "YYO02": "把同期人物收进原生圆窗，保留圆外描边和弧形主题。",
    "YYO03": "缩小同期人物画面，依次显示上下两处重点。",
    "YYO04": "用原生闪现及聚光灯引出人物和短标题。",
    "YYO05": "收窄为圆角人物窗，沿用原生上下文字布局。",
    "YYO07": "放大同期画面，将短标题叠在人物身后。",
}
YY_OPENING_DEPENDENCIES = ("font-aa4560dd8fe56457", "model-01eb6a29a5c4d8edb30b")
YY_OPENING_CAPTION_INTENT = "yy-opening-caption-intent.json"
YY_OPENING_CAPTION_BASELINE = 1230
YY_OPENING_ENTRY_EVENT = "/events/image_in"
YY_OPENING_COMPOSITOR_SHA256 = (
    "ec5115f41bbb44c034bccc66b06169f92a389d4a270eea8c6c6cd1d2e3472038"
)
# The latest visible native text uses the upper 560 px of the original canvas.
_TEXT_BAND_END = 560
_FIXED_TEXT_WINDOWS = {
    "YYO01": ("subtitle", 5, 15),
    "YYO02": ("topic", 3, 12),
    "YYO03": ("topic", 6, 15),
    "YYO04": ("topic", 12, 22),
    "YYO05": ("topic", 7, 15),
    "YYO07": ("topic", 7, 18),
}


def yy_opening_binding(group: str) -> str:
    role, start, end = _FIXED_TEXT_WINDOWS[group]
    return (
        "presenter 绑定本期原片。image_in 绑定本段首词。"
        f"{role} 的实录首词须位于原生固定入场窗口第 {start} 至 {end} 帧。"
        "title_in 和 question_in 绑定对应实录首词，落定绑定各自的后续实录边界。"
        "四个文字槽均使用实录，未绘制的槽可复用同段实录短语。"
        + (
            "question 只用于问号的词点，原生画面不绘制问句文字。"
            if group == "YYO07"
            else ""
        )
        + ("圆角窗须在原生第 11 帧前落定。" if group == "YYO05" else "")
    )


def validate_yy_opening(
    group: str, anchors: dict, frames: int, transcript: Transcript
) -> None:
    text = {row["path"].removeprefix("/content/"): row for row in anchors["text"]}
    events = {row["path"].removeprefix("/events/"): row for row in anchors["events"]}
    limits = {
        "topic": 6 if group == "YYO02" else 8,
        "title": 3,
        "question": 5,
        "subtitle": 12,
    }
    if any(
        not 1 <= len(text[role]["text"]) <= limit or "\n" in text[role]["text"]
        for role, limit in limits.items()
    ):
        raise ValueError("Native opening text exceeds the original role capacity")
    value = {event: row["value"] for event, row in events.items()}
    if not (
        value["image_in"] == 0 < value["image_settle"] < frames
        and events["image_in"]["edge"] == "start"
        and value["title_in"] < value["question_in"]
    ) or (group == "YYO05" and value["image_settle"] > 11):
        raise ValueError(
            "Original image motion must start at the scene boundary and settle"
        )
    for role in ("title", "question"):
        event = events[role + "_in"]
        settled = value[role + "_settle"]
        visible_length = (
            1 if group == "YYO07" and role == "question" else len(text[role]["text"])
        )
        if not (
            event["edge"] == "start"
            and event["token_id"] == text[role]["token_ids"][0]
            and event["value"] < settled
            and settled + max(4, math.ceil(visible_length * 30 / 16)) <= frames
        ):
            raise ValueError(
                "Original title or question needs its measured word and reading time"
            )

    role, lower, upper = _FIXED_TEXT_WINDOWS[group]
    token_id = text[role]["token_ids"][0]
    measured = next(
        token.start_ms for token in transcript.tokens if token.id == token_id
    )
    first_frame = round((measured - anchors["clock"]["start_ms"]) * 30 / 1000)
    if not lower <= first_frame <= upper:
        raise ValueError("Spoken term misses the fixed original text entry window")


def require_clean_yy_source(
    template: dict | None, source_subtitles: str, unavailable: dict[str, list[str]]
) -> None:
    if template and source_subtitles != "none":
        for slot in template["slots"]:
            group = slot["group_id"]
            if group in YY_OPENING_GROUPS:
                unavailable.setdefault(group, []).append("clean_source_required")


def yy_opening_entry_frame(shot: dict, fps: int) -> int:
    if (
        shot["group_id"] not in YY_OPENING_GROUPS
        or shot["layer"] != "scene"
        or shot["rect"] != [0, 0, 1, 1]
        or shot["config"]["events"]["image_in"] != 0
    ):
        raise ValueError("Expected the original YYO scene starting on the source clock")
    # The pinned original compositor enables the layer at gte(t,start).
    return math.ceil(shot["start_seconds"] * fps - 1e-6)


def verify_yy_opening_captions(root: Path, report: dict) -> dict:
    """Keep actual native libass ink below the audited scene text band."""
    episode = read_json(root / "episode.json")
    indices = read_json(root / YY_OPENING_CAPTION_INTENT)["shots"]
    if not indices or report["status"] != "passed":
        raise ValueError("The original layout report must be available")
    captions = episode["captions"]
    ink = report["caption_ink"]
    if len(captions) != len(ink) or not all(
        (row["start"], row["end"]) == (caption["start_seconds"], caption["end_seconds"])
        and len(row["box"]) == 4
        for caption, row in zip(captions, ink, strict=True)
    ):
        raise ValueError("The caption ink does not match the actual episode timeline")
    text_bottom = math.ceil(episode["output"]["height"] * _TEXT_BAND_END / 640)
    checks = []
    for index in indices:
        shot = episode["shots"][index]
        group = shot["group_id"]
        if (
            group not in YY_OPENING_GROUPS
            or shot["layer"] != "scene"
            or shot["rect"] != [0, 0, 1, 1]
        ):
            raise ValueError("Expected an audited full-frame original YYO opening")
        active = [
            row
            for row in ink
            if row["start"] < shot["end_seconds"] and shot["start_seconds"] < row["end"]
        ]
        if not active or min(row["box"][1] for row in active) < text_bottom:
            raise ValueError("Main caption ink enters the original YYO text band")
        checks.append(
            {
                "shot": index,
                "group_id": group,
                "caption_events_checked": len(active),
                "smallest_gap_px": min(row["box"][1] for row in active) - text_bottom,
            }
        )
    return {"status": "passed", "native_text_band_end_px": text_bottom, "shots": checks}
