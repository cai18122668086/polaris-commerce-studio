"""Word timing and caption clearance for original YY opening scenes."""

import math
from pathlib import Path

from .motion_library import read_json
from .video_editing_contracts import Transcript
from .video_editing_yy6_scenes import YY6_GROUPS, YY6_NUMBER_UNITS, YY6_SOUND_EVENTS

YY_OPENING_GROUPS = {
    "YYO01": "从缩小的人物画面展开，保留原生放大及标题。",
    "YYO02": "把同期人物收进原生圆窗，保留圆外描边和弧形主题。",
    "YYO03": "缩小同期人物画面，依次显示上下两处重点。",
    "YYO04": "用原生闪现及聚光灯引出人物和短标题。",
    "YYO05": "收窄为圆角人物窗，沿用原生上下文字布局。",
    "YYO07": "放大同期画面，将短标题叠在人物身后。",
}
YY_OPENING_EXPANDED_GROUPS = {
    **YY_OPENING_GROUPS,
    "YYO06": "从虚焦中推出同期人物，用原生竖排依次突出两个实录词组。",
    "YYO08": "用原生推近镜头把画面重点从上方标题转到下方实录短句。",
    "YY6O04": "把同期人物从矩形转成圆窗，再突出实录明确说出的数量和单位。",
}
YY_OPENING_ALL_GROUPS = {**YY_OPENING_EXPANDED_GROUPS, **YY6_GROUPS}
YY_OPENING_DEPENDENCIES = ("font-aa4560dd8fe56457", "model-01eb6a29a5c4d8edb30b")
YY_OPENING_CAPTION_INTENT = "yy-opening-caption-intent.json"
YY_OPENING_CAPTION_BASELINE = 1230
YY_OPENING_LOWER_CAPTION_BASELINE = 1266
YY_OPENING_ENTRY_EVENTS = {
    **dict.fromkeys(YY_OPENING_EXPANDED_GROUPS, "/events/image_in"),
    **{group: next(iter(events)) for group, events in YY6_SOUND_EVENTS.items()},
    "YYO08": "/events/title_in",
    "YY6O04": "/events/rectangle/0",
}
YY_OPENING_SOURCE_EVENTS = {**YY_OPENING_ENTRY_EVENTS, "YYO08": "/events/image_in"}
YY_OPENING_COMPOSITOR_SHA256 = (
    "ec5115f41bbb44c034bccc66b06169f92a389d4a270eea8c6c6cd1d2e3472038"
)
# In the 360x640 originals, the tear and flash layouts carry lower number text.
_TEXT_BAND_END = 560
YY_OPENING_LOWER_TEXT_BANDS = {"YY6O02": 582, "YY6O05": 590}
_FIXED_TEXT_WINDOWS = {
    "YYO01": (("subtitle", 5, 15),),
    "YYO02": (("topic", 3, 12),),
    "YYO03": (("topic", 6, 15),),
    "YYO04": (("topic", 12, 22),),
    "YYO05": (("topic", 7, 15),),
    "YYO06": (("topic", 5, 10), ("title", 12, 18)),
    "YYO07": (("topic", 7, 18),),
    "YYO08": (("question", 30, 40),),
}
_SPECIAL_BINDINGS = {
    "YYO06": (
        "presenter 绑定同期原片，image_in 绑定本段首词。"
        "topic 最多三字，实录首词位于本段第 5 至 10 帧。"
        "title 最多两字，实录首词位于第 12 至 18 帧。"
        "title_in 实际触发 subtitle，须绑定 subtitle 实录首词。"
        "question_in 绑定 question 实录首词，画面只显示问号。"
    ),
    "YYO08": (
        "presenter 绑定同期原片，image_in 绑定本段首词。"
        "title_in 实际触发 topic，须绑定第 22 帧前的 topic 实录首词，"
        "并在原生第 35 帧前留出阅读时间。"
        "topic 最多六字，question 最多五字，question 实录首词位于第 30 至 40 帧。"
        "question_in 和 question_settle 记录同一短句的词点，原生入场保留固定帧。"
        "title 和 subtitle 仍绑定实录，可复用同段短语。"
    ),
    "YY6O04": (
        "presenter 绑定同期原片。rectangle/0 绑定本段首词。"
        "矩形需在原生第 30 帧内落定。"
        "topic、issue、subtitle 的入场分别绑定各自实录首词。"
        "count 与 unit 必须是实录中相邻的一位数量和一个单位字。"
        "response 从数量首词开始。"
        "矩形需先落定再转成圆窗，数量入场须晚于圆窗开始，各动作留出落定及阅读时间。"
        "若为规格对照，在 relation_items 分别绑定前后两项的实录和各自文字槽。"
    ),
}


def yy_opening_binding(group: str) -> str:
    if group in _SPECIAL_BINDINGS:
        return _SPECIAL_BINDINGS[group]
    ((role, start, end),) = _FIXED_TEXT_WINDOWS[group]
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
    if group == "YY6O04":
        _validate_number_opening(text, events, frames, transcript)
        return
    limits = {
        "topic": 6 if group == "YYO02" else 8,
        "title": 3,
        "question": 5,
        "subtitle": 12,
    }
    if group == "YYO06":
        limits.update(topic=3, title=2)
    elif group == "YYO08":
        limits.update(topic=6)
    _validate_capacity(text, limits)
    value = {event: row["value"] for event, row in events.items()}
    if not (
        value["image_in"] == 0 < value["image_settle"] < frames
        and events["image_in"]["edge"] == "start"
        and value["title_in"] < value["question_in"]
    ) or (group == "YYO05" and value["image_settle"] > 11):
        raise ValueError(
            "Original image motion must start at the scene boundary and settle"
        )
    if group == "YYO08" and value["title_in"] >= 22:
        raise ValueError("Original top title must begin before the push-in")
    title_role = {"YYO06": "subtitle", "YYO08": "topic"}.get(group, "title")
    for action, role in (("title", title_role), ("question", "question")):
        event = events[action + "_in"]
        settled = value[action + "_settle"]
        visible_length = (
            1
            if group in {"YYO06", "YYO07"} and role == "question"
            else len(text[role]["text"])
        )
        last_frame = (
            min(frames, 35) if group == "YYO08" and action == "title" else frames
        )
        # In YYO08 the question metadata records speech; the animation settles at 40.
        reading_start = 40 if group == "YYO08" and action == "question" else settled
        if not (
            event["edge"] == "start"
            and event["token_id"] == text[role]["token_ids"][0]
            and event["value"] < settled
            and reading_start + _reading_frames(visible_length) <= last_frame
        ):
            raise ValueError(
                "Original title or question needs its measured word and reading time"
            )

    for role, lower, upper in _FIXED_TEXT_WINDOWS[group]:
        _validate_fixed_word(text[role], lower, upper, anchors, transcript)


def _reading_frames(length: int) -> int:
    return max(4, math.ceil(length * 30 / 16))


def _validate_capacity(text: dict, limits: dict[str, int]) -> None:
    if any(
        not 1 <= len(text[role]["text"]) <= limit or "\n" in text[role]["text"]
        for role, limit in limits.items()
    ):
        raise ValueError("Native opening text exceeds the original role capacity")


def _validate_fixed_word(
    text: dict, lower: int, upper: int, anchors: dict, transcript: Transcript
) -> None:
    token_id = text["token_ids"][0]
    measured = next(
        token.start_ms for token in transcript.tokens if token.id == token_id
    )
    first_frame = round((measured - anchors["clock"]["start_ms"]) * 30 / 1000)
    if not lower <= first_frame <= upper:
        raise ValueError("Spoken term misses the fixed original text entry window")


def _validate_number_opening(
    text: dict, events: dict, frames: int, transcript: Transcript
) -> None:
    _validate_capacity(
        text, {"topic": 5, "issue": 8, "count": 1, "unit": 1, "subtitle": 7}
    )
    ids = [token.id for token in transcript.tokens]
    count, unit = text["count"], text["unit"]
    if (
        count["text"] not in "0123456789零一二两三四五六七八九十"
        or unit["text"] not in YY6_NUMBER_UNITS
        or ids.index(count["token_ids"][-1]) + 1 != ids.index(unit["token_ids"][0])
    ):
        raise ValueError("Original number needs a single spoken quantity and its unit")
    value = {event: row["value"] for event, row in events.items()}
    if not (
        value["rectangle/0"] == 0 < value["rectangle/1"] <= 30
        and value["rectangle/1"] <= value["circle/0"] < value["circle/1"] < frames
        and events["rectangle/0"]["edge"] == "start"
        and value["topic/0"] < value["issue/0"] < value["response/0"]
        and value["circle/0"] <= value["response/0"] <= value["subtitle/0"]
    ):
        raise ValueError(
            "Original rectangle, circle and number need ordered word clocks"
        )
    for action, role in (
        ("topic", "topic"),
        ("issue", "issue"),
        ("response", "count"),
        ("subtitle", "subtitle"),
    ):
        event = events[action + "/0"]
        settled = value[action + "/1"]
        length = 2 if action == "response" else len(text[role]["text"])
        if not (
            event["edge"] == "start"
            and event["token_id"] == text[role]["token_ids"][0]
            and event["value"] < settled
            and settled + _reading_frames(length) <= frames
        ):
            raise ValueError(
                "Original number scene needs each spoken role and reading time"
            )


def require_clean_yy_source(
    template: dict | None, source_subtitles: str, unavailable: dict[str, list[str]]
) -> None:
    if template and source_subtitles != "none":
        for slot in template["slots"]:
            group = slot["group_id"]
            if group in YY_OPENING_ALL_GROUPS:
                unavailable.setdefault(group, []).append("clean_source_required")


def yy_opening_entry_frame(shot: dict, fps: int, path: str | None = None) -> int:
    group = shot["group_id"]
    if (
        group not in YY_OPENING_ALL_GROUPS
        or shot["layer"] != "scene"
        or shot["rect"] != [0, 0, 1, 1]
    ):
        raise ValueError("Expected the original YYO scene starting on the source clock")
    events = shot["config"]["events"]
    if group in YY6_GROUPS:
        actions = YY6_SOUND_EVENTS[group]
        entry = YY_OPENING_ENTRY_EVENTS[group]
        path = path or entry
        if fps != 30 or path not in actions or events[entry.split("/")[2]][0] != 0:
            raise ValueError("Original YY6 sound needs a measured visible entrance")
        local = events[path.split("/")[2]][0] + actions[path]
        origin = shot["start_seconds"] / (1 / fps)
        frame = max(math.ceil(origin - 1e-6), math.floor(origin) + local)
        if frame >= math.ceil(shot["end_seconds"] * fps - 1e-6):
            raise ValueError("Original YY6 action starts after the rendered scene")
        return frame
    source_start = events["rectangle"][0] if group == "YY6O04" else events["image_in"]
    if source_start != 0:
        raise ValueError("Original YYO picture must start at its scene boundary")
    local = 0
    if group == "YYO08":
        # The top title first has positive opacity one frame after its event.
        local = events["title_in"] + 1
        if not 1 <= local <= 22:
            raise ValueError("Original top title must begin before the push-in")
    elif group == "YY6O04":
        # Local frame zero still uses the full-size rectangle at its rest position.
        if not 0 < events["rectangle"][1] <= 30:
            raise ValueError("Original rectangle must reach its initial pose promptly")
        local = 1
    # Original setpts truncates the positive origin. The enable gate still rounds up.
    origin = round(shot["start_seconds"] * 1000) * fps
    return max((origin + 999) // 1000, origin // 1000 + local)


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
    text_bands = []
    checks = []
    for index in indices:
        shot = episode["shots"][index]
        group = shot["group_id"]
        if (
            group not in YY_OPENING_ALL_GROUPS
            or shot["layer"] != "scene"
            or shot["rect"] != [0, 0, 1, 1]
        ):
            raise ValueError("Expected an audited full-frame original YYO opening")
        text_bottom = math.ceil(
            episode["output"]["height"]
            * YY_OPENING_LOWER_TEXT_BANDS.get(group, _TEXT_BAND_END)
            / 640
        )
        text_bands.append(text_bottom)
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
    return {
        "status": "passed",
        "native_text_band_end_px": max(text_bands),
        "shots": checks,
    }
