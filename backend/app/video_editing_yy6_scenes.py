"""Verified picture roles and measured speech for the original YY6 openings."""

import math

from .video_editing_contracts import Transcript
from .video_editing_materials import project_image_digests
from .video_editing_word_bindings import emphasis_text

YY6_GROUPS = {
    "YY6O01": "暗底圆窗转描边人物，用原问号提出实录中的问题，再引出数量。",
    "YY6O02": "保留原撕纸与人物前景，将两张本期静态背景按原生图层展开。",
    "YY6O03": "保留聚光灯及人物缩放，先显示实录短指标，再显示后续数量。",
    "YY6O05": "保留原闪现及聚焦，口播先说条件，再说相关数量。",
    "YY6O06": "保留电视纹理与竖排主题，由实录数量触发中间数字和单位。",
}
YY6_BACKGROUND = "/media/background/path"
YY6_ROOM = "/media/room/path"
YY6_COUNT_GLYPHS = "0123456789零一二两三四五六七八九十"
YY6_NUMBER_UNITS = (
    "个瓶罐盒包袋件份套杯张只条根把单双次遍步种类层款档点"
    "斤克吨升秒分刻时天周月年米寸元块折度成"
)
YY6_SOUND_EVENTS = {
    "YY6O01": {"/events/topic/0": 0, "/events/person_expand/0": 1},
    "YY6O02": {"/events/reveal_light/0": 0, "/events/response/0": 1},
    "YY6O03": {"/events/person_scale/0": 0, "/events/response/0": 1},
    "YY6O05": {"/events/flash/0": 0, "/events/focus/0": 1},
    "YY6O06": {"/events/texture/0": 0, "/events/central/0": 1},
}
_ACTION_BINDINGS = {
    "YY6O01": "topic 从本段首词开始。circle_shrink 先完成，再 person_expand。"
    "question 对应实际疑问词，问号保留原图形。kicker 用数量旁的实录短词。",
    "YY6O02": "tear 和 reveal_light 从本段首词开始，撕纸完成后 restore，"
    "再用 response 引出数量。room 和 background 用两张不同的本期静态图片。",
    "YY6O03": "person_scale 从本段首词开始，spotlight 先于 restore。"
    "metric 是早于主数量的实录短指标，metric 入场绑自己的首词。"
    "kicker 用数量旁的实录短词。",
    "YY6O05": "flash 从本段首词开始，先闪现再 focus，随后 restore。",
    "YY6O06": "texture 从本段首词开始，先出现竖排短语，再 blur，"
    "central 从数量首词开始并在虚焦动作中交接。",
}
_QUESTION_MARKS = "谁吗么哪何怎啥？?"
_SIZE_WORDS = {"大", "小"}


def yy6_slots(group: str) -> tuple[str, ...]:
    return (YY6_BACKGROUND, YY6_ROOM) if group == "YY6O02" else (YY6_BACKGROUND,)


def yy6_binding(group: str) -> str:
    return (
        "presenter 绑定同期原片，background 使用本期静态背景。"
        "topic、issue、subtitle 的入场绑实录首词。数量和单位从 "
        "yy6_scene_inputs 中选择本段的一组词；response 或 central 绑数量首词。"
        "所有动作尾部使用实录词边界，文字落定后保留阅读时间。"
        "规格对照须用 relation_items 分开绑定各项实录和对应文字槽。"
        + _ACTION_BINDINGS[group]
    )


def yy6_scene_inputs(
    template: dict | None,
    transcript: Transcript,
    cards: list[dict],
    unavailable: dict[str, list[str]],
) -> dict:
    groups = {slot["group_id"] for slot in (template or {}).get("slots", [])}
    groups &= YY6_GROUPS.keys()
    if not groups:
        return {}
    images = project_image_digests(cards)
    quantities = yy6_quantity_pairs(transcript)
    count = len(set(images.values()))
    for group in sorted(groups):
        if count < len(yy6_slots(group)):
            unavailable.setdefault(group, []).append(
                "distinct_opening_backgrounds_required"
            )
        if not quantities:
            unavailable.setdefault(group, []).append("measured_quantity_required")
        if group == "YY6O01" and not any(
            marker in token.text
            for token in transcript.tokens
            for marker in _QUESTION_MARKS
        ):
            unavailable.setdefault(group, []).append("measured_question_required")
    return {
        "background_image_ids": sorted(images),
        "quantity_pairs": [
            {"count_token_id": count_id, "unit_token_id": unit_id}
            for count_id, unit_id in quantities
        ],
    }


def yy6_quantity_pairs(transcript: Transcript) -> list[tuple[str, str]]:
    quantities = []
    tokens = transcript.tokens
    for i, token in enumerate(tokens[:-1]):
        glyph = token.text.strip()
        if len(glyph) != 1 or glyph not in YY6_COUNT_GLYPHS:
            continue
        j = i + 1
        if tokens[j].text.strip() in _SIZE_WORDS:
            j += 1
        if j < len(tokens) and all(
            tokens[index].start_ms - tokens[index - 1].end_ms <= 300
            for index in range(i + 1, j + 1)
        ):
            unit = emphasis_text(tokens[j].text, "omit_sentence_punctuation")
            if len(unit) == 1 and unit in YY6_NUMBER_UNITS:
                quantities.append((token.id, tokens[j].id))
    return quantities


def _motion_visibility(
    group: str, events: dict[str, tuple[int, int]], frames: int
) -> dict[str, int]:
    start = {key: pair[0] for key, pair in events.items()}
    end = {key: pair[1] for key, pair in events.items()}
    final = "central" if group == "YY6O06" else "response"
    if not start["topic"] <= start["issue"] < start[final]:
        raise ValueError(
            "Original opening needs its spoken topic, issue and quantity in order"
        )
    if group == "YY6O01":
        valid = (
            end["circle_shrink"] <= start["person_expand"] <= start[final]
            and end["person_expand"] <= end[final]
        )
        visible = {
            "topic": end["person_expand"],
            "issue": end["person_expand"],
            "question": end["person_expand"],
        }
    elif group == "YY6O02":
        valid = (
            start["tear"] == start["reveal_light"] == 0
            and end["tear"] <= start["restore"] <= start[final]
            and end["restore"] <= end[final]
        )
        visible = {"topic": end[final], "issue": end[final]}
    elif group == "YY6O03":
        valid = (
            end["spotlight"] <= start["restore"] <= start[final]
            and end["person_scale"] <= end["restore"]
            and start["metric"] < start[final]
        )
        visible = {"topic": end[final], "issue": end[final], "metric": end[final]}
    elif group == "YY6O05":
        valid = (
            end["flash"] <= start["focus"]
            and end["focus"] <= start["restore"] <= start[final]
        )
        visible = {"topic": end["issue"], "issue": end[final]}
    else:
        valid = (
            end["texture"] <= end["topic"]
            and start["blur"] <= start[final] <= end["blur"] <= end[final]
        )
        visible = {"topic": end[final], "issue": end[final]}
    if not valid:
        raise ValueError(
            "Measured words do not preserve the original opening's phase order"
        )
    return {**visible, final: frames, "subtitle": frames}


def validate_yy6_opening(
    group: str,
    anchors: dict,
    frames: int,
    transcript: Transcript,
    capacity: dict,
) -> None:
    text = {row["path"].removeprefix("/content/"): row for row in anchors["text"]}
    marks = {row["path"]: row for row in anchors["events"]}
    tokens = {token.id: token for token in transcript.tokens}
    names = {path.split("/")[2] for path in marks}
    events = {
        name: (marks[f"/events/{name}/0"]["value"], marks[f"/events/{name}/1"]["value"])
        for name in names
    }
    entry, *actions = YY6_SOUND_EVENTS[group]
    if (
        marks[entry]["value"] != 0
        or any(marks[path]["edge"] != "start" for path in (entry, *actions))
        or any(not 0 <= left < right <= frames for left, right in events.values())
    ):
        raise ValueError("Original opening needs ordered measured frame ranges")
    if any(
        not 1 <= len(row["text"]) <= capacity[role] or "\n" in row["text"]
        for role, row in text.items()
    ):
        raise ValueError("Native opening text exceeds the original role capacity")
    count, unit = text["count"], text["unit"]
    if (
        count["text"] not in YY6_COUNT_GLYPHS
        or unit["text"] not in YY6_NUMBER_UNITS
        or len(count["token_ids"]) != 1
        or len(unit["token_ids"]) != 1
        or (count["token_ids"][0], unit["token_ids"][0])
        not in yy6_quantity_pairs(transcript)
    ):
        raise ValueError(
            "Original opening needs one measured quantity and its own unit"
        )
    final = "central" if group == "YY6O06" else "response"
    visibility = _motion_visibility(group, events, frames)
    if group == "YY6O01":
        q = marks["/events/question/0"]
        if q["edge"] != "start" or not any(
            mark in tokens[q["token_id"]].text for mark in _QUESTION_MARKS
        ):
            raise ValueError(
                "Original question glyph requires a spoken question anchor"
            )
    if "kicker" in text:
        lead = tokens[text["kicker"]["token_ids"][0]].start_ms
        if abs(lead - marks[f"/events/{final}/0"]["measured_anchor_ms"]) > 1500:
            raise ValueError("Opening kicker must describe the nearby spoken quantity")
    if "metric" in text:
        metric = text["metric"]
        label = metric["text"]
        if (
            len(label) != 2
            or label[0] not in YY6_COUNT_GLYPHS
            or label[1] not in YY6_NUMBER_UNITS
            or tokens[metric["token_ids"][-1]].end_ms
            > tokens[count["token_ids"][0]].start_ms
        ):
            raise ValueError("Original spotlight needs its earlier spoken metric")
    for action, until in visibility.items():
        first, settle = events[action]
        role = "count" if action == final else action
        length = (
            1
            if role == "question"
            else 2
            if role == "count"
            else len(text[role]["text"])
        )
        if role != "question":
            mark = marks[f"/events/{action}/0"]
            if (
                mark["edge"] != "start"
                or mark["token_id"] != text[role]["token_ids"][0]
            ):
                raise ValueError(
                    "Original opening text must enter with its actual first word"
                )
        if first + max(5, math.ceil(length * 30 / 16)) > until or settle + 3 > until:
            raise ValueError("Original opening label needs visible reading time")
