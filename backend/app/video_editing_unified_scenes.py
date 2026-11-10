"""Measured narration for original unified statement and comparison scenes."""

import math
from pathlib import Path

from .motion_library import read_json
from .video_editing_contracts import SemanticBeat, Transcript, TranscriptToken
from .video_editing_cut_scenes import (
    CUT_CAPTION_BANDS,
    CUT_GROUPS,
    CUT_SOUND_MODES,
    CUT_TEMPLATE_ID,
)
from .video_editing_native_content import (
    NUMBER_GROUP,
    YEAR_GROUP,
    number_glyphs,
    year_display,
    year_glyphs,
)
from .video_editing_story_panels import (
    PANEL_BOARDS,
    PANEL_CAPTION_BANDS,
    PANEL_GROUPS,
    PANEL_SOUNDS,
    PANEL_SOURCE,
    PANEL_TEMPLATE_ID,
)
from .video_editing_word_bindings import emphasis_text

UNIFIED_TEMPLATE_ID = "unified-argument-v1"
UNIFIED_EXPANDED_TEMPLATE_ID = "unified-argument-v2"
UNIFIED_TEMPLATES = frozenset(
    {
        UNIFIED_TEMPLATE_ID,
        UNIFIED_EXPANDED_TEMPLATE_ID,
        CUT_TEMPLATE_ID,
        PANEL_TEMPLATE_ID,
    }
)
UNIFIED_DESIGN_ID = "tengli-unified-argument-v1"
UNIFIED_CAPTION_INTENT = "unified-argument-caption-intent.json"
UNIFIED_WINDOW_GROUP = "Z-M03"
UNIFIED_WINDOW_CAPTION_BASELINE = 980
UNIFIED_PRESENTER = "/media/presenter/path"
UNIFIED_VIDEO_VARIANTS = frozenset({"Z-M02", "Z-M03", "Z-M04"})
PRESENTER_VIDEO_GROUPS = UNIFIED_VIDEO_VARIANTS | PANEL_BOARDS
UNIFIED_MEDIA_PATHS = {
    **dict.fromkeys(("Z-M01", "Z-M14", *UNIFIED_VIDEO_VARIANTS), UNIFIED_PRESENTER),
    "W-R05": "/media/background/path",
    NUMBER_GROUP: "/media/source/path",
    **PANEL_SOURCE,
}
UNIFIED_EXPANDED_GROUPS = {
    "W-R05": (
        "在同期原景依次推出两项并列论点。",
        "first 和 second 各用一至六字，first_in 和 second_in 锚定各自首词。",
    ),
    NUMBER_GROUP: (
        "用同一实录画面镂空显示前后两个同单位数值。",
        "每项绑定完整短句和其中的数值及单位。black_in、second_number 各锚定数值首词，"
        "label 使用同一单位的实录词。先留出原黑场渐变，再进入第二个数字。",
    ),
}
YEAR_FONT = "font-06b2048c592b1dae"
YEAR_BINDING = (
    "年份须是实录中连续四位数字加年。前后各取一至两字，背衬事件取随后实录两字。"
    "body_frame、year_frame 和 back_frame 对应各自首词，"
    "clear_frame 取可读后的一处实录词尾。"
)
UNIFIED_GROUPS = {
    "Z-M01": (
        "在同期原景中，先后推出同一段的两个重点。",
        "phrase0、phrase1 依次对准两段实际短语。",
    ),
    "Z-M02": (
        "暗角收束一段完整判断，再恢复同期原画。",
        "三段原生短字幕分别绑定实录起止。"
        "darken 从第一段首词开始，release 从第三段首词开始。",
    ),
    "Z-M03": (
        "矩形同期人物窗配合三个并列要点，最后收束。",
        "title 从本段首词开始，item0 至 item2 对应三个并列项，summary 对应实录结论。",
    ),
    "Z-M04": (
        "同期人物圆窗移位，承接前后两个实录重点。",
        "phrase0 从本段首词开始，move 与 phrase1 一起绑定第二项。",
    ),
    "Z-M09": (
        "原生全屏不等式区分实录中不可等同的两项。",
        "premise 从本段首词开始，relation_in 取实录反转，answer_in 取后项首词。",
    ),
    "Z-M10": (
        "使用实录明确说出的一位数字作为原数字卡。",
        "number 限实录 1 至 9，body 先介绍且包含该数字，"
        "action 对应其后行动，settle_in 绑定末段实录词点。",
    ),
    "Z-M14": (
        "在同期人物圆窗四周依次加入三个并列实录词组。",
        "三个 item 事件各自对准完整实录短语的首词。",
    ),
}
UNIFIED_SOUNDS = {
    "Z-M01": {"phrase0": "ease", "phrase1": "ease"},
    "Z-M02": {"darken": "visible", "release": "visible"},
    "Z-M03": {
        "title": "scene",
        "item0": "ease",
        "item1": "ease",
        "item2": "ease",
        "summary": "ease",
    },
    "Z-M04": {"phrase0": "scene", "move": "ease"},
    "Z-M09": {"relation_in": "ease", "answer_in": "visible"},
    "Z-M10": {"number_in": "ease", "action_in": "ease"},
    "Z-M14": {"item0": "ease", "item1": "ease", "item2": "ease"},
    "W-R05": {"first_in": "ease", "second_in": "ease"},
    NUMBER_GROUP: {"black_in": "ease", "second_number": "ease"},
    **CUT_SOUND_MODES,
    **PANEL_SOUNDS,
}
_TEXT_BINDINGS = {
    "Z-M01": {"phrases/0": "phrase0", "phrases/1": "phrase1"},
    "Z-M03": {
        "title": "title",
        "labels/0": "item0",
        "labels/1": "item1",
        "labels/2": "item2",
        "summary": "summary",
    },
    "Z-M04": {"phrases/0": "phrase0", "phrases/1": "phrase1"},
    "Z-M09": {"answer": "answer_in"},
    "Z-M10": {"number": "number_in", "action": "action_in", "body": "body_in"},
    "Z-M14": {"words/0": "item0", "words/1": "item1", "words/2": "item2"},
    "W-R05": {"first": "first_in", "second": "second_in"},
}
_TEXT_LIMITS = {
    "Z-M01": (9, 9),
    "Z-M03": (12, 5, 5, 5, 7),
    "Z-M04": (9, 9),
    "Z-M09": (12, 12),
    "Z-M10": (1, 6, 13),
    "Z-M14": (5, 5, 5),
    "W-R05": (6, 6),
}
_REQUIRED_RELATIONS = {
    "Z-M03": ("parallel", ("labels/0", "labels/1", "labels/2")),
    "Z-M09": ("contrast", ("premise", "answer")),
    "Z-M14": ("parallel", ("words/0", "words/1", "words/2")),
    "W-R05": ("parallel", ("first", "second")),
    NUMBER_GROUP: ("contrast", ("captions/0", "captions/1")),
}
UNIFIED_SCENE_GROUPS = (
    UNIFIED_GROUPS.keys()
    | UNIFIED_EXPANDED_GROUPS.keys()
    | CUT_GROUPS.keys()
    | PANEL_GROUPS.keys()
)
_CAPTION_BANDS = {
    "Z-M02": (800, 960),
    UNIFIED_WINDOW_GROUP: (530, 745),
    "Z-M10": (825, 960),
    "Z-M14": (850, 960),
    NUMBER_GROUP: (850, 960),
    **CUT_CAPTION_BANDS,
    **PANEL_CAPTION_BANDS,
}
_EVENT_PREFIX = "/timing/events/"


def unified_binding(group: str) -> str:
    media = UNIFIED_MEDIA_PATHS.get(group)
    return (
        (
            media.split("/")[2] + " 使用同期口播原片。"
            if media
            else "沿用原整帧底板，口播继续。"
        )
        + (UNIFIED_GROUPS | UNIFIED_EXPANDED_GROUPS)[group][1]
        + (
            "用 relation_items 按实录顺序绑定每项及对应文字槽。"
            if group in _REQUIRED_RELATIONS
            else ""
        )
        + "各文字槽只取实录完整短语，按原容量留出阅读时间。"
    )


def unified_sound_paths(group: str) -> tuple[str, ...]:
    return tuple(_EVENT_PREFIX + event for event in UNIFIED_SOUNDS.get(group, {}))


def unified_presenter_template(template: dict) -> dict:
    return {
        **template,
        "media": {
            **template["media"],
            "presenter": {
                **template["media"]["presenter"],
                "kind": "video",
                "offset_seconds": 0,
                "duration_seconds": 1,
                "end_policy": "error",
            },
        },
    }


def require_clean_unified_source(
    template: dict | None, source_subtitles: str, unavailable: dict[str, list[str]]
) -> None:
    if template and template["id"] in UNIFIED_TEMPLATES and source_subtitles != "none":
        for slot in template["slots"]:
            if (group := slot["group_id"]) in UNIFIED_SCENE_GROUPS:
                unavailable.setdefault(group, []).append("clean_source_required")


def require_spoken_year(
    template: dict | None, transcript: Transcript, unavailable: dict[str, list[str]]
) -> None:
    if not template or template["id"] != UNIFIED_EXPANDED_TEMPLATE_ID:
        return
    tokens = transcript.tokens
    for end, token in enumerate(tokens):
        if not emphasis_text(token.text, "omit_sentence_punctuation").endswith("年"):
            continue
        for start in range(max(0, end - 4), end + 1):
            if _continuous_year(tokens[start : end + 1]):
                return
    unavailable.setdefault(YEAR_GROUP, []).append("spoken_year_required")


def _continuous_year(tokens: list[TranscriptToken]) -> bool:
    spoken = "".join(t.text.strip() for t in tokens).rstrip("，。！？、；：,.!?;:")
    return year_display(spoken) is not None and all(
        b.start_ms - a.end_ms < 250 for a, b in zip(tokens, tokens[1:], strict=False)
    )


def validate_year_anchors(anchors: dict, transcript: Transcript) -> None:
    year = year_glyphs(anchors)
    rows = {row["path"]: row for row in anchors["text"]}
    events = {row["path"]: row for row in anchors["events"]}
    positions = {t.id: i for i, t in enumerate(transcript.tokens)}
    prefix, suffix, back = (
        rows[f"/content/{key}"] for key in ("prefix", "suffix", "event")
    )
    body, year_in, back_in, clear = (
        events[f"/events/{key}_frame"] for key in ("body", "year", "back", "clear")
    )
    first, last = (positions[year["token_ids"][i]] for i in (0, -1))
    if (
        not _continuous_year(transcript.tokens[first : last + 1])
        or positions[prefix["token_ids"][-1]] != first - 1
        or positions[suffix["token_ids"][0]] != last + 1
        or positions[suffix["token_ids"][-1]] >= positions[back["token_ids"][0]]
        or any(
            not minimum <= len(row["text"]) <= 2 or "\n" in row["text"]
            for row, minimum in ((prefix, 1), (suffix, 1), (back, 2))
        )
        or not _starts(body, prefix)
        or not _starts(back_in, back)
        or clear["edge"] != "end"
        or not body["value"] < year_in["value"] < back_in["value"]
        or clear["value"]
        < max(body["value"] + 12, year_in["value"] + 12, back_in["value"] + 8)
    ):
        raise ValueError(
            "Original year needs its actual neighboring words and three motion phases"
        )


def _starts(anchor: dict, text: dict) -> bool:
    return anchor["edge"] == "start" and anchor["token_id"] == text["token_ids"][0]


def _reading_time(text: dict) -> float:
    return max(0.22, len(text["text"]) / 15)


def _validate_judgment(text: dict, events: dict, duration: float) -> None:
    values: list[tuple[float, float]] = []
    for i in range(3):
        prefix = f"/content/captions/{i}"
        label = text[f"captions/{i}/text"]
        start, end = events[prefix + "/start"], events[prefix + "/end"]
        if (
            not _starts(start, label)
            or end["edge"] != "end"
            or end["token_id"] != label["token_ids"][-1]
            or not 1 <= len(label["text"]) <= 14
            or "\n" in label["text"]
            or not start["value"] + _reading_time(label) <= end["value"] <= duration
            or (values and values[-1][1] > start["value"])
        ):
            raise ValueError(
                "Judgment captions must retain three measured spoken ranges"
            )
        values.append((start["value"], end["value"]))
    if not (
        events[_EVENT_PREFIX + "darken"]["value"] == values[0][0]
        and events[_EVENT_PREFIX + "release"]["value"] == values[2][0]
        and values[2][0] - values[0][0] >= 0.4
    ):
        raise ValueError(
            "Original vignette must enter and release on the spoken phases"
        )


def _validate_relation(beat: SemanticBeat) -> None:
    if beat.group_id not in _REQUIRED_RELATIONS:
        return
    relation, expected = _REQUIRED_RELATIONS[beat.group_id]
    if (
        beat.relation != relation
        or len(beat.relation_items) != len(expected)
        or any(
            "/content/" + path not in item.native_text_paths
            for path, item in zip(expected, beat.relation_items, strict=True)
        )
    ):
        raise ValueError(
            "Map each original visual item to its actual relation and word range"
        )


def validate_unified_anchors(beat: SemanticBeat, anchors: dict) -> None:
    group = beat.group_id
    text = {row["path"].removeprefix("/content/"): row for row in anchors["text"]}
    events = {row["path"]: row for row in anchors["events"]}
    clock = anchors["clock"]
    duration = (clock["end_ms"] - clock["start_ms"]) / 1000
    if not 0.8 <= duration <= 15 or any(
        events[_EVENT_PREFIX + action]["edge"] != "start"
        for action in UNIFIED_SOUNDS[group]
    ):
        raise ValueError("Original unified scene needs measured motion entrances")
    if group == "Z-M02":
        _validate_judgment(text, events, duration)
        return
    _validate_relation(beat)
    times = {
        path.removeprefix(_EVENT_PREFIX): row["value"] for path, row in events.items()
    }
    if group == NUMBER_GROUP:
        first, second = number_glyphs(anchors)
        if (
            not first["unit"]
            or first["display_text"] == second["display_text"]
            or not 0 < times["black_in"] <= times["second_number"] - 0.35
            or times["second_number"] > duration - 0.5
            or any(not 1 <= len(text[f"captions/{i}"]["text"]) <= 12 for i in range(2))
        ):
            raise ValueError(
                "The two amounts need distinct values and time for the original roll"
            )
        return
    roles = _TEXT_BINDINGS[group]
    ordered_text = ["premise", "answer"] if group == "Z-M09" else list(roles)
    if any(
        not 1 <= len(text[path]["text"]) <= limit or "\n" in text[path]["text"]
        for path, limit in zip(ordered_text, _TEXT_LIMITS[group], strict=True)
    ) or any(
        not _starts(events[_EVENT_PREFIX + action], text[path])
        for path, action in roles.items()
    ):
        raise ValueError(
            "Native words must fit their slots and enter at the spoken starts"
        )
    if group == "W-R05":
        valid = times["first_in"] + 0.35 <= times["second_in"] <= duration - 0.32
    elif group in {"Z-M01", "Z-M04"}:
        valid = times["phrase0"] + _reading_time(text["phrases/0"]) <= times["phrase1"]
        if group == "Z-M04":
            valid = (
                valid and times["phrase0"] == 0 and times["move"] == times["phrase1"]
            )
    elif group in {"Z-M03", "Z-M14"}:
        active = [times[f"item{i}"] for i in range(3)]
        valid = all(a + 0.16 <= b for a, b in zip(active, active[1:], strict=False))
        if group == "Z-M03":
            valid = (
                valid
                and times["title"] == 0
                and active[0] >= 0.20
                and active[-1] + 0.20 <= times["summary"]
            )
    elif group == "Z-M09":
        valid = (
            text["premise"]["token_ids"][0] == beat.first_token_id
            and _reading_time(text["premise"])
            <= times["relation_in"]
            < times["answer_in"]
            and times["answer_in"] + 0.12 <= times["answer_settled"] <= duration - 0.20
        )
    else:
        number, body = text["number"], text["body"]
        valid = (
            number["text"] in "123456789"
            and number["token_ids"][0] in body["token_ids"]
            and times["body_in"]
            <= times["number_in"]
            <= times["action_in"]
            <= times["settle_in"]
            <= duration - 0.26
        )
    if not valid or any(
        times[action] + _reading_time(text[path]) > duration
        for path, action in roles.items()
    ):
        raise ValueError(
            "Measured words do not leave time for the original action and reading"
        )


def unified_action_frame(shot: dict, fps: int, path: str) -> int:
    group = shot["group_id"]
    event = path.removeprefix(_EVENT_PREFIX)
    if (
        fps != 30
        or path != _EVENT_PREFIX + event
        or shot["layer"] != "scene"
        or shot["rect"] != [0, 0, 1, 1]
        or event not in UNIFIED_SOUNDS[group]
    ):
        raise ValueError("Original unified sound needs its full-frame native action")
    name, sep, index = event.partition("/")
    value = shot["config"]["timing"]["events"][name]
    at = (value[int(index)] if sep else value) * fps
    mode = UNIFIED_SOUNDS[group][event]
    local = (
        0
        if mode == "scene"
        else math.floor(at + 1e-7) + 1
        if mode == "ease"
        else math.ceil(at - 1e-7)
    )
    origin = shot["start_seconds"] / (1 / fps)
    frame = max(math.ceil(origin - 1e-6), math.floor(origin) + local)
    if frame >= math.ceil(shot["end_seconds"] * fps - 1e-6):
        raise ValueError("Original unified sound enters after its visible scene")
    return frame


def split_unified_caption_lanes(
    captions: list[dict], windows: list[tuple[float, float, int]]
) -> list[dict]:
    result = []
    for caption in captions:
        start, end = caption["start_seconds"], caption["end_seconds"]
        overlaps = [(a, b, y) for a, b, y in windows if start < b and a < end]
        if len({y for _, _, y in overlaps}) < 2:
            result.append(caption)
            continue
        changes = [
            a
            for (_, _, before), (a, _, after) in zip(
                overlaps, overlaps[1:], strict=False
            )
            if before != after
        ]
        points = [start, *changes, end]
        result.extend(
            {**caption, "start_seconds": a, "end_seconds": b}
            for a, b in zip(points, points[1:], strict=False)
        )
    return result


def verify_unified_captions(root: Path, report: dict) -> dict:
    episode = read_json(root / "episode.json")
    indices = read_json(root / UNIFIED_CAPTION_INTENT)["shots"]
    ink = report["caption_ink"]
    captions = episode["captions"]
    if (
        not indices
        or report["status"] != "passed"
        or len(ink) != len(captions)
        or any(
            (row["start"], row["end"]) != (cap["start_seconds"], cap["end_seconds"])
            or len(row["box"]) != 4
            for row, cap in zip(ink, captions, strict=True)
        )
    ):
        raise ValueError("Original unified scenes require their rendered caption ink")
    checks = []
    for index in indices:
        shot = episode["shots"][index]
        group = shot["group_id"]
        height = episode["output"]["height"]
        top, bottom = _CAPTION_BANDS.get(group, (820, 960))
        top_px = math.ceil(height * top / 960)
        bottom_px = math.floor(height * bottom / 960)
        active = [
            row["box"]
            for row in ink
            if row["start"] < shot["end_seconds"] and shot["start_seconds"] < row["end"]
        ]
        gap = min(
            (min(box[1] - top_px, bottom_px - box[3]) for box in active), default=-1
        )
        if (
            group not in UNIFIED_SCENE_GROUPS
            or shot["layer"] != "scene"
            or shot["rect"] != [0, 0, 1, 1]
            or gap < 0
        ):
            raise ValueError("Main subtitle ink enters the original unified text band")
        checks.append(
            {
                "group_id": group,
                "caption_band_px": [top_px, bottom_px],
                "smallest_gap_px": gap,
            }
        )
    return {"status": "passed", "shots": checks}
